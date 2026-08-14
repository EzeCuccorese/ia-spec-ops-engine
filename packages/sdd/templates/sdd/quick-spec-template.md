# ⚡ Especificación Rápida (Quick Spec): {{bugfix_title}}

**ID**: `quick-{{timestamp}}`  
**Tipo**: CORRECCIÓN DE BUG / HOTFIX ACELERADO  
**Fecha**: {{date}}  

---

## 🎯 1. Descripción del Problema
{{problem_description}}

---

## 🔍 2. Causa Raíz Identificada
- **Archivo Afectado**: [`{{file_path}}`](file://{{absolute_path}})
- **Detalle Técnico**: {{root_cause}}

---

## 🛠️ 3. Plan de Solución Mínimo (Minimal Implementation)
1. **Contrato / Firma**: {{contract_changes}}
2. **Prueba Unitaria (Red)**: {{test_description}}
3. **Lógica de Remediación (Green)**: {{implementation_steps}}

---

## ✅ 4. Criterios de Aceptación y Verificación
- [ ] La prueba unitaria reproduce el caso de fallo y ahora pasa en verde.
- [ ] No se introducen efectos secundarios ni regresiones en la suite de pruebas.
- [ ] Linter estático verificado sin advertencias.
