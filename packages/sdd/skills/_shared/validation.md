### Paso 0: Validar Parámetros y Estado Inicial
1. **Validación de Feature**: Verificar si existe un feature activo en `.specify/feature.json` o si se pasa como argumento.
2. **Confirmación Interactiva**: Si hay ambigüedades, consultar al usuario mediante `AskUserQuestion`.
3. **Alineación con Constitución**: Consultar `.specify/constitution/constitution.md` antes de generar entregables.
