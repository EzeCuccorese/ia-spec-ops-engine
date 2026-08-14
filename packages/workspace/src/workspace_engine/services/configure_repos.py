#!/usr/bin/env python3
"""
workspace_engine.services.configure_repos — Configuración interactiva de branches y pre-validación de worktrees.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import termios
import threading
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from workspace_engine.services.tui_utils import _read_key, _resolve_cursor
from workspace_engine.utils import Color


@dataclass
class RepoConfig:
    name: str
    mode: str            # "new" o "existing"
    branch: str
    parent: Optional[str]  # None para modo existing

    @property
    def is_remote_only(self) -> bool:
        """Indica si la branch existe únicamente en el remoto (origin)."""
        return getattr(self, '_remote_only', False)

    def mark_remote_only(self):
        object.__setattr__(self, '_remote_only', True)


def fetch_branches(repo_path: Path, skip_fetch: bool = False) -> List[str]:
    """Obtiene branches locales y remotas del repositorio deduplicadas."""
    if not skip_fetch:
        subprocess.run(
            ['git', '-C', str(repo_path), 'fetch', '--quiet', 'origin'],
            capture_output=True,
        )

    result = subprocess.run(
        ['git', '-C', str(repo_path), 'branch', '-a', '--format=%(refname:short)'],
        capture_output=True, text=True,
    )

    seen: set = set()
    branches: List[str] = []
    for raw in result.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if raw.startswith('remotes/origin/'):
            name = raw[len('remotes/origin/'):]
        elif raw.startswith('origin/'):
            name = raw[len('origin/'):]
        else:
            name = raw
        if name in ('HEAD', ''):
            continue
        if name not in seen:
            seen.add(name)
            branches.append(name)

    return sorted(branches)


def _git(repo_path: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', '-C', str(repo_path)] + list(args),
        capture_output=True, text=True,
    )


def _parse_worktrees(porcelain: str) -> List[Tuple[Path, str]]:
    """Parsea la salida de 'git worktree list --porcelain'."""
    result = []
    current_path = None
    current_branch = None
    for line in porcelain.splitlines():
        if line.startswith('worktree '):
            current_path = Path(line[len('worktree '):])
            current_branch = None
        elif line.startswith('branch '):
            current_branch = line[len('branch '):]
        elif line == '' and current_path:
            if current_branch:
                result.append((current_path, current_branch))
            current_path = None
            current_branch = None
    if current_path and current_branch:
        result.append((current_path, current_branch))
    return result


def pre_validate(configs: List[RepoConfig], repo_paths: Dict[str, Path]) -> List[str]:
    """Pre-valida todas las configuraciones de repositorio antes de crear worktrees."""
    errors: List[str] = []

    for cfg in configs:
        repo_path = repo_paths.get(cfg.name)
        if repo_path is None or not repo_path.exists():
            detail = f' en {repo_path}' if repo_path else ''
            errors.append(f'{cfg.name}: directorio del repositorio no encontrado{detail}')
            continue

        if cfg.mode == 'existing':
            wt_result = _git(repo_path, 'worktree', 'list', '--porcelain')
            branch_ref = f'refs/heads/{cfg.branch}'
            worktrees = _parse_worktrees(wt_result.stdout)
            for wt_path, wt_branch in worktrees:
                if wt_branch == branch_ref and str(wt_path) != str(repo_path):
                    errors.append(
                        f'{cfg.name}: la rama \'{cfg.branch}\' ya está activa en otro worktree: {wt_path}'
                    )

            local = _git(repo_path, 'rev-parse', '--verify', f'refs/heads/{cfg.branch}')
            if local.returncode != 0:
                remote = _git(repo_path, 'rev-parse', '--verify', f'refs/remotes/origin/{cfg.branch}')
                if remote.returncode == 0:
                    cfg.mark_remote_only()

        elif cfg.mode == 'new' and cfg.parent:
            local = _git(repo_path, 'rev-parse', '--verify', cfg.parent)
            if local.returncode != 0:
                remote = _git(repo_path, 'rev-parse', '--verify', f'refs/remotes/origin/{cfg.parent}')
                if remote.returncode != 0:
                    errors.append(
                        f'{cfg.name}: la rama origen \'{cfg.parent}\' no existe localmente ni en origin'
                    )

    return errors


def _tty_write(tty_fd, s: str):
    tty_fd.write(s.encode())


def _branch_config_panel(
    repo_name: str,
    workspace_name: str,
    repo_path: Path,
    tty_fd,
    old_attrs,
    repo_index: int = 0,
    repo_total: int = 1,
    initial: Optional[RepoConfig] = None,
    fetch_cache_minutes: int = 5,
    pre_fetch_thread: Optional[threading.Thread] = None,
    pre_fetch_cache: Optional[dict] = None,
) -> Optional[RepoConfig]:
    """Muestra el panel de configuración de branch para un repositorio."""
    mode = initial.mode if initial else 'new'
    new_branch_name = initial.branch if (initial and initial.mode == 'new') else workspace_name
    new_branch_cur = len(new_branch_name)
    parent_branch = (initial.parent or 'main') if (initial and initial.mode == 'new') else 'main'
    parent_filter = ''
    parent_filter_cur = 0
    exist_branch = initial.branch if (initial and initial.mode == 'existing') else ''
    exist_filter = ''
    exist_filter_cur = 0
    focused = 0
    editing = False
    name_error = ''
    exist_error = ''
    fetching = False
    last_fetched_str = ''

    branches: List[str] = []
    branches_loaded = False
    dropdown_idx = -1
    dropdown_scroll = 0

    def _confirm_row(m: str) -> int:
        return 2 if m == 'new' else 1

    def _is_picker(m: str, f: int) -> bool:
        return (m == 'new' and f == 1) or (m == 'existing' and f == 0)

    def _should_skip_fetch() -> bool:
        fh = repo_path / '.git' / 'FETCH_HEAD'
        if fh.exists():
            return (time.time() - fh.stat().st_mtime) < (fetch_cache_minutes * 60)
        return False

    def _suggestions(text: str) -> List[str]:
        if not text:
            return list(branches)
        t = text.lower()
        return [b for b in branches if t in b.lower()]

    def _branch_exists(name: str) -> bool:
        return name in branches

    def _get_list_height(rows: int) -> int:
        return max(5, rows - 17)

    def _value_row(label: str, value: str, placeholder: str, is_focused: bool, cols: int) -> str:
        max_val = max(10, cols - len(label) - 6)
        if value:
            disp = value[-max_val:] if len(value) > max_val else value
            val_str = disp
        else:
            ph = placeholder[:max_val]
            val_str = f'{Color.DIM}{ph}{Color.RESET}'
        if is_focused:
            return f'{Color.BOLD}{Color.CYAN}▶ {label}{Color.RESET}{val_str}\r\n'
        return f'  {Color.DIM}{label}{Color.RESET}{val_str}\r\n'

    def _text_edit_row(label: str, text: str, cur: int, cols: int) -> str:
        max_val = max(10, cols - len(label) - 6)
        start = max(0, cur - max_val)
        before = text[start:cur]
        after  = text[cur:start + max_val]
        return f'  {Color.BOLD}{label}{before}\x00{after}{Color.RESET}\r\n'

    def _filter_row(text: str, cur: int, cols: int) -> str:
        max_val = max(10, cols - 12)
        start = max(0, cur - max_val)
        before = text[start:cur]
        after  = text[cur:start + max_val]
        return f'  {Color.BOLD}Filtro{Color.RESET}  {before}\x00{after}\r\n'

    def _list_lines(text: str, d_idx: int, scroll: int, list_height: int, cols: int) -> List[str]:
        sugg = _suggestions(text)
        total = len(sugg)
        if not sugg:
            return [f'  {Color.DIM}(ninguna rama coincide){Color.RESET}\r\n']
        window = sugg[scroll:scroll + list_height]
        lines = []
        for i, s in enumerate(window):
            abs_i = scroll + i
            is_sel = abs_i == d_idx
            sh = ' ↑' if (i == 0 and scroll > 0) else (' ↓' if (i == len(window) - 1 and (scroll + list_height) < total) else '  ')
            max_name = max(10, cols - 7)
            s_disp = s[:max_name] if len(s) > max_name else s
            if is_sel:
                lines.append(f'  {Color.BOLD}{Color.CYAN}▶ {s_disp}{Color.RESET}{sh}\r\n')
            else:
                lines.append(f'    {s_disp}{sh}\r\n')
        return lines

    def _top_hint() -> str:
        if editing:
            if mode == 'new' and focused == 0:
                return 'Escribe el nombre de la rama   ENTER siguiente campo   ESC volver'
            if _is_picker(mode, focused):
                return 'Escribe para filtrar   ↑↓ seleccionar   ENTER confirmar   ESC volver'
        return '↑↓ navegar   ENTER editar / confirmar   ← → cambiar modo   ESC volver'

    def _picker_section(ftext: str, fcur: int, lh: int, sep_s: str, cols: int) -> List[str]:
        out: List[str] = []
        out.append(f'{sep_s}\r\n')
        out.append(_filter_row(ftext, fcur, cols))
        out.append('\r\n')
        ll = _list_lines(ftext, dropdown_idx, dropdown_scroll, lh, cols)
        out.extend(ll)
        for _ in range(lh - len(ll)):
            out.append('\r\n')
        out.append(f'{sep_s}\r\n')
        return out

    def _render():
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(60, cols)
        sep_w = cols - 2
        lh = _get_list_height(rows)
        sep_d = Color.BOLD + Color.CYAN + '═' * sep_w + Color.RESET
        sep_s = Color.DIM + '─' * sep_w + Color.RESET
        cr = _confirm_row(mode)

        out = ['\033[H\033[J']
        out.append(f'{sep_d}\r\n')

        counter = f'[{repo_index + 1}/{repo_total}]'
        max_rn = sep_w - len(counter) - 5
        rn_disp = repo_name[:max_rn] if len(repo_name) > max_rn else repo_name
        out.append(f'{Color.BOLD}  {rn_disp}  {counter}{Color.RESET}\r\n')
        if last_fetched_str:
            out.append(f'  {Color.DIM}actualizado: {last_fetched_str}{Color.RESET}\r\n')
        out.append(f'{sep_d}\r\n')

        if fetching:
            out.append(f'\r\n  {Color.YELLOW}Consultando ramas remotas en origin…{Color.RESET}\r\n')
            _tty_write(tty_fd, ''.join(out))
            return

        out.append(f'  {Color.DIM}{_top_hint()}{Color.RESET}\r\n')
        out.append('\r\n')

        if mode == 'new':
            out.append(f'  Modo:  {Color.BOLD}● Nueva{Color.RESET}   ○ Existente   {Color.DIM}(← → para alternar){Color.RESET}\r\n')
            out.append('\r\n')

            if editing and focused == 0:
                out.append(_text_edit_row('Nombre de Rama ', new_branch_name, new_branch_cur, cols))
            else:
                out.append(_value_row('Nombre de Rama ', new_branch_name, '', focused == 0, cols))
            if name_error:
                out.append(f'  {Color.RED}{name_error[:cols - 4]}{Color.RESET}\r\n')
            else:
                out.append('\r\n')

            if editing and focused == 1:
                out.extend(_picker_section(parent_filter, parent_filter_cur, lh, sep_s, cols))
            else:
                out.append(_value_row('Rama Origen    ', parent_branch, 'main', focused == 1, cols))

        else:
            out.append(f'  Modo:  ○ Nueva   {Color.BOLD}● Existente{Color.RESET}   {Color.DIM}(← → para alternar){Color.RESET}\r\n')
            out.append('\r\n')

            out.append(_value_row('Nombre de Rama ', exist_branch, 'presiona ENTER para seleccionar rama', focused == 0, cols))
            if exist_error:
                out.append(f'  {Color.RED}{exist_error[:cols - 4]}{Color.RESET}\r\n')
            else:
                out.append('\r\n')

            if editing and focused == 0:
                out.extend(_picker_section(exist_filter, exist_filter_cur, lh, sep_s, cols))

        out.append('\r\n')
        if focused == cr and not editing:
            out.append(f'{Color.BOLD}{Color.GREEN}▶ [ Confirmar ]{Color.RESET}\r\n')
        else:
            out.append(f'  {Color.DIM}[ Confirmar ]{Color.RESET}\r\n')

        frame, cur_seq = _resolve_cursor(''.join(out))
        _tty_write(tty_fd, frame + cur_seq)

    fetching = True
    _render()
    if pre_fetch_thread is not None and pre_fetch_thread.is_alive():
        pre_fetch_thread.join()
    if pre_fetch_cache is not None and repo_name in pre_fetch_cache:
        branches = pre_fetch_cache[repo_name]
    else:
        branches = fetch_branches(repo_path, skip_fetch=_should_skip_fetch())
    branches_loaded = True
    fetching = False
    fh = repo_path / '.git' / 'FETCH_HEAD'
    if fh.exists():
        ts = datetime.datetime.fromtimestamp(fh.stat().st_mtime)
        last_fetched_str = ts.strftime('%d/%m/%Y %H:%M:%S')

    if mode == 'new' and _branch_exists(new_branch_name):
        name_error = 'la rama ya existe — cambia a Existente o elige otro nombre'
        focused = 0

    while True:
        _render()
        key = _read_key(tty_fd)

        if key == b'\x1b':
            if editing:
                editing = False
                parent_filter = ''
                exist_filter = ''
                dropdown_idx = -1
                dropdown_scroll = 0
            else:
                return None
        elif key == b'\x03':
            _tty_write(tty_fd, '\033[?25h')
            termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
            sys.exit(130)
        elif key in (b'\x1b[C', b'\x1b[D'):
            if editing:
                d = -1 if key == b'\x1b[D' else 1
                if mode == 'new' and focused == 0:
                    new_branch_cur = max(0, min(len(new_branch_name), new_branch_cur + d))
                elif mode == 'new' and focused == 1:
                    parent_filter_cur = max(0, min(len(parent_filter), parent_filter_cur + d))
                elif mode == 'existing' and focused == 0:
                    exist_filter_cur = max(0, min(len(exist_filter), exist_filter_cur + d))
            else:
                if mode == 'new':
                    mode = 'existing'
                    focused = 0
                    exist_error = ''
                    dropdown_idx = -1
                    dropdown_scroll = 0
                else:
                    mode = 'new'
                    focused = 0
                    name_error = ''
                    dropdown_idx = -1
                    dropdown_scroll = 0
        elif key in (b'\x1b[H', b'\x1b[1~'):
            if editing:
                if mode == 'new' and focused == 0:   new_branch_cur = 0
                elif mode == 'new' and focused == 1:  parent_filter_cur = 0
                elif mode == 'existing':              exist_filter_cur = 0
        elif key in (b'\x1b[F', b'\x1b[4~'):
            if editing:
                if mode == 'new' and focused == 0:   new_branch_cur = len(new_branch_name)
                elif mode == 'new' and focused == 1:  parent_filter_cur = len(parent_filter)
                elif mode == 'existing':              exist_filter_cur = len(exist_filter)
        elif key == b'\x1b[3~':
            if editing:
                if mode == 'new' and focused == 0 and new_branch_cur < len(new_branch_name):
                    new_branch_name = new_branch_name[:new_branch_cur] + new_branch_name[new_branch_cur + 1:]
                    name_error = ''
                elif mode == 'new' and focused == 1 and parent_filter_cur < len(parent_filter):
                    parent_filter = parent_filter[:parent_filter_cur] + parent_filter[parent_filter_cur + 1:]
                    dropdown_idx = -1
                    dropdown_scroll = 0
                elif mode == 'existing' and focused == 0 and exist_filter_cur < len(exist_filter):
                    exist_filter = exist_filter[:exist_filter_cur] + exist_filter[exist_filter_cur + 1:]
                    exist_error = ''
                    dropdown_idx = -1
                    dropdown_scroll = 0
        elif key == b'\x1b[A':
            if editing and _is_picker(mode, focused):
                if dropdown_idx > 0:
                    dropdown_idx -= 1
                    if dropdown_idx < dropdown_scroll:
                        dropdown_scroll = dropdown_idx
                elif dropdown_idx == 0:
                    dropdown_idx = -1
                    dropdown_scroll = 0
            elif not editing and focused > 0:
                focused -= 1
        elif key == b'\x1b[B':
            if editing and _is_picker(mode, focused):
                ftext = parent_filter if (mode == 'new' and focused == 1) else exist_filter
                sugg = _suggestions(ftext)
                if sugg:
                    next_idx = dropdown_idx + 1
                    if next_idx < len(sugg):
                        dropdown_idx = next_idx
                        _, rows = shutil.get_terminal_size(fallback=(80, 24))
                        if dropdown_idx >= dropdown_scroll + _get_list_height(rows):
                            dropdown_scroll = dropdown_idx - _get_list_height(rows) + 1
            elif not editing:
                cr = _confirm_row(mode)
                if focused < cr:
                    focused += 1
        elif key in (b'\r', b'\n', b''):
            cr = _confirm_row(mode)
            if not editing:
                if focused == cr:
                    if mode == 'new':
                        if not new_branch_name:
                            name_error = 'El nombre de la rama no puede estar vacío'
                            focused = 0
                        elif _branch_exists(new_branch_name):
                            name_error = 'la rama ya existe — cambia a Existente o elige otro nombre'
                            focused = 0
                        else:
                            return RepoConfig(name=repo_name, mode='new', branch=new_branch_name, parent=parent_branch)
                    else:
                        if exist_branch:
                            return RepoConfig(name=repo_name, mode='existing', branch=exist_branch, parent=None)
                        else:
                            exist_error = 'Selecciona una rama primero'
                            focused = 0
                else:
                    editing = True
                    if _is_picker(mode, focused):
                        if mode == 'new':
                            parent_filter = ''
                        else:
                            exist_filter = ''
                        dropdown_idx = -1
                        dropdown_scroll = 0
            else:
                if mode == 'new' and focused == 0:
                    if not new_branch_name:
                        name_error = 'El nombre de la rama no puede estar vacío'
                    elif _branch_exists(new_branch_name):
                        name_error = 'la rama ya existe — cambia a Existente o elige otro nombre'
                    else:
                        name_error = ''
                        editing = False
                        focused = 1
                elif mode == 'new' and focused == 1:
                    sugg = _suggestions(parent_filter)
                    if branches_loaded and dropdown_idx >= 0 and dropdown_idx < len(sugg):
                        parent_branch = sugg[dropdown_idx]
                        parent_filter = ''
                        parent_filter_cur = 0
                        editing = False
                        focused = cr
                        dropdown_idx = -1
                        dropdown_scroll = 0
                    elif parent_filter in sugg:
                        parent_branch = parent_filter
                        parent_filter = ''
                        parent_filter_cur = 0
                        editing = False
                        focused = cr
                        dropdown_idx = -1
                        dropdown_scroll = 0
                elif mode == 'existing' and focused == 0:
                    sugg = _suggestions(exist_filter)
                    if branches_loaded and dropdown_idx >= 0 and dropdown_idx < len(sugg):
                        exist_branch = sugg[dropdown_idx]
                        exist_error = ''
                    elif exist_filter in sugg:
                        exist_branch = exist_filter
                        exist_error = ''
                    else:
                        exist_error = 'Selecciona una rama de la lista'
                        exist_branch = ''

                    if exist_branch:
                        exist_filter = ''
                        exist_filter_cur = 0
                        editing = False
                        focused = cr
                        dropdown_idx = -1
                        dropdown_scroll = 0
        elif key in (b'\x7f', b'\x08'):
            if editing:
                if mode == 'new' and focused == 0 and new_branch_cur > 0:
                    new_branch_name = new_branch_name[:new_branch_cur - 1] + new_branch_name[new_branch_cur:]
                    new_branch_cur -= 1
                    name_error = ''
                elif mode == 'new' and focused == 1 and parent_filter_cur > 0:
                    parent_filter = parent_filter[:parent_filter_cur - 1] + parent_filter[parent_filter_cur:]
                    parent_filter_cur -= 1
                    dropdown_idx = -1
                    dropdown_scroll = 0
                elif mode == 'existing' and focused == 0 and exist_filter_cur > 0:
                    exist_filter = exist_filter[:exist_filter_cur - 1] + exist_filter[exist_filter_cur:]
                    exist_filter_cur -= 1
                    exist_error = ''
                    dropdown_idx = -1
                    dropdown_scroll = 0
        else:
            ch = key.decode('utf-8', errors='ignore')
            if ch.isprintable() and editing:
                if mode == 'new' and focused == 0:
                    new_branch_name = new_branch_name[:new_branch_cur] + ch + new_branch_name[new_branch_cur:]
                    new_branch_cur += 1
                    name_error = ''
                elif mode == 'new' and focused == 1:
                    parent_filter = parent_filter[:parent_filter_cur] + ch + parent_filter[parent_filter_cur:]
                    parent_filter_cur += 1
                    dropdown_idx = -1
                    dropdown_scroll = 0
                elif mode == 'existing' and focused == 0:
                    exist_filter = exist_filter[:exist_filter_cur] + ch + exist_filter[exist_filter_cur:]
                    exist_filter_cur += 1
                    exist_error = ''
                    dropdown_idx = -1
                    dropdown_scroll = 0


def _confirm_panel(configs: List[RepoConfig], tty_fd, old_attrs) -> bool:
    """Panel de confirmación final de la configuración de repositorios."""
    def _render():
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        cols = max(60, cols)
        sep_w = cols - 2
        sep_d = Color.BOLD + Color.CYAN + '═' * sep_w + Color.RESET
        out = ['\033[H\033[J']
        out.append(f'{sep_d}\r\n')
        out.append(f'{Color.BOLD}  Confirmar Workspace{Color.RESET}\r\n')
        out.append(f'{sep_d}\r\n')
        out.append(f'  {Color.DIM}ENTER confirmar   ESC volver{Color.RESET}\r\n')
        out.append('\r\n')
        for cfg in configs:
            out.append(f'  {Color.BOLD}{cfg.name}{Color.RESET}\r\n')
            if cfg.mode == 'new':
                out.append(f'    {Color.DIM}nueva rama:{Color.RESET}  {cfg.branch}  {Color.DIM}desde{Color.RESET}  {cfg.parent or "main"}\r\n')
            else:
                out.append(f'    {Color.DIM}existente:{Color.RESET}  {cfg.branch}\r\n')
            out.append('\r\n')
        out.append(f'{Color.BOLD}{Color.GREEN}▶ [ Confirmar ]{Color.RESET}\r\n')
        _tty_write(tty_fd, ''.join(out))

    while True:
        _render()
        key = _read_key(tty_fd)
        if key == b'\x1b':
            return False
        elif key == b'\x03':
            termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
            sys.exit(130)
        elif key in (b'\r', b'\n', b''):
            return True


def configure_repos(
    workspace_name: str,
    repo_names: List[str],
    repo_paths: Dict[str, Path],
    fetch_cache_minutes: int = 5,
) -> Optional[List[RepoConfig]]:
    """Configura interactivamente las ramas para cada repositorio seleccionado."""
    if not repo_names:
        return []

    prefetch_cache: dict = {}

    def _prefetch(rname: str) -> None:
        try:
            rp = repo_paths[rname]
            fh = rp / '.git' / 'FETCH_HEAD'
            skip = fh.exists() and (time.time() - fh.stat().st_mtime) < (fetch_cache_minutes * 60)
            prefetch_cache[rname] = fetch_branches(rp, skip_fetch=skip)
        except Exception:
            prefetch_cache[rname] = ([], [])

    prefetch_threads: dict = {}
    for rname in repo_names:
        t = threading.Thread(target=_prefetch, args=(rname,), daemon=True)
        prefetch_threads[rname] = t
        t.start()

    try:
        tty_fd = open('/dev/tty', 'rb+', buffering=0)
    except Exception:
        # Fallback default para entornos no interactivos
        return [RepoConfig(name=r, mode='new', branch=workspace_name, parent='main') for r in repo_names]

    old_attrs = termios.tcgetattr(tty_fd)
    configs = [None] * len(repo_names)
    confirmed = False
    try:
        tty.setraw(tty_fd.fileno())
        _tty_write(tty_fd, '\033[?25l\033[?1049h')
        i = 0
        while True:
            if i < len(repo_names):
                cfg = _branch_config_panel(
                    repo_name=repo_names[i],
                    workspace_name=workspace_name,
                    repo_path=repo_paths[repo_names[i]],
                    tty_fd=tty_fd,
                    old_attrs=old_attrs,
                    repo_index=i,
                    repo_total=len(repo_names),
                    initial=configs[i],
                    fetch_cache_minutes=fetch_cache_minutes,
                    pre_fetch_thread=prefetch_threads.get(repo_names[i]),
                    pre_fetch_cache=prefetch_cache,
                )
                if cfg is None:
                    if i == 0:
                        return None
                    i -= 1
                else:
                    configs[i] = cfg
                    i += 1
            else:
                if _confirm_panel(configs, tty_fd, old_attrs):
                    confirmed = True
                    break
                else:
                    i = len(repo_names) - 1
    finally:
        _tty_write(tty_fd, '\033[?1049l\033[?25h')
        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_attrs)
        tty_fd.close()

    if not confirmed:
        return None

    errors = pre_validate(configs, repo_paths)
    if errors:
        print(f'\n{Color.RED}❌ Falló la pre-validación:{Color.RESET}', file=sys.stderr)
        for err in errors:
            print(f'   {Color.RED}• {err}{Color.RESET}', file=sys.stderr)
        sys.exit(1)

    return configs
