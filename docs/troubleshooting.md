# Troubleshooting

Un ejecutable ausente en `spec verify` no cuenta como `PASS`: instalá las
dependencias y repetí el check. Para revisar módulos instalados:

```bash
ia-spec-ops-engine install --components governance,spec,workspace
```

Si la desinstalación de un agente se bloquea, el bloque administrado fue
modificado y se preserva para evitar pérdida de datos.
