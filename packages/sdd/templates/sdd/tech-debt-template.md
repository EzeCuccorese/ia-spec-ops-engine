# 📊 Catálogo de Deuda Técnica, Bugs y Anti-Patrones

**Repositorio**: `{{repo_name}}`  
**Fecha de Auditoría**: {{date}}  
**Estado General**: {{status}}  
**Puntaje de Deuda**: {{critical_count}} Críticos, {{high_count}} Altos, {{medium_count}} Medios, {{low_count}} Bajos  

---

## 🎯 Resumen Ejecutivo
{{executive_summary}}

---

## 📈 Matriz de Prioridad e Impacto
- 🔴 **CRÍTICO**: Vulnerabilidades de seguridad, secretos expuestos, riesgo de pérdida de datos.
- 🟠 **ALTO**: Lógica de negocio crítica sin tests unitarios, consultas N+1, bordes HTTP sin contratos.
- 🟡 **MEDIO**: Clases Dios, código duplicado, falta de logger estructurado.
- 🟢 **BAJO**: TODOs informativos, comentarios obsoletos, inconsistencias menores de formato.

---

## 📑 Catálogo Detallado de Hallazgos y Planes de Ataque

### 🔴 Hallazgos Críticos

#### `[TD-001]` {{finding_title}}
- **Categoría**: {{category}}
- **Ubicación**: [`{{file_path}}:L{{line_number}}`](file://{{absolute_path}}#L{{line_number}})
- **Descripción**: {{description}}
- **Impacto Potencial**: {{impact}}
- **Plan de Ataque y Remediación**:
  1. Paso 1: {{step_1}}
  2. Paso 2: {{step_2}}
- **Comando de Remediación SDD (Copiar y Pegar)**:
  ```bash
  /sdd-quick "Corregir [TD-001]: {{short_description}} en {{file_path}}"
  ```

---

## 🛠️ Plan de Acción Sugerido
1. **Fase 1 (Inmediata)**: Resolver hallazgos 🔴 Críticos mediante `/sdd-quick`.
2. **Fase 2 (Corto Plazo)**: Implementar contratos Zod/DTOs y tests para hallazgos 🟠 Altos.
3. **Fase 3 (Mantenimiento)**: Refactorizar módulos 🟡 Medios en próximos ciclos.
