# DevScripts - Herramientas para Desarrollo

Este repositorio contiene una colección de scripts útiles para automatizar tareas comunes de desarrollo, despliegue y gestión de configuración.

## Requisitos Generales

- Python 3.6 o superior
- Dependencias específicas para cada script (ver documentación individual)

## Scripts Disponibles

### null-api.py

Script para interactuar con la API de Null Platform. Permite gestionar parámetros y variables de entorno en Null Platform.

**Requisitos:**
- Python 3.6+
- Paquetes: `requests`, `tabulate`
- Token de acceso a Null Platform (`NULL_TOKEN`)

**Comandos:**
- `list-all-params`: Lista todos los parámetros de una aplicación
- `create-vars-from-env`: Crea variables desde archivos .env
- `create-vars-from-yml`: Crea variables desde un archivo YAML
- `delete-all-params`: Elimina todos los parámetros de una aplicación

[Ver documentación detallada](null-api.py)

### build-project.py

Automatiza el proceso de construcción de proyectos Java (Maven o Gradle).

**Características:**
- Actualiza el repositorio local (git pull, push, fetch tags)
- Detecta automáticamente la herramienta de construcción (Maven o Gradle)
- Configura la versión de Java requerida
- Ejecuta el comando de construcción
- Muestra la versión del proyecto

### deploy-to-namespace.py

Facilita el despliegue de proyectos a diferentes namespaces en Kubernetes.

**Características:**
- Lista proyectos disponibles
- Monitorea el flujo de trabajo de despliegue
- Configura Java automáticamente
- Despliega a múltiples namespaces

### set-java.py

Detecta, instala y configura la versión de Java requerida para un proyecto.

**Características:**
- Detecta la versión de Java requerida desde archivos de proyecto (Maven o Gradle)
- Utiliza sdkman para instalar y configurar Java
- Verifica que la versión correcta esté configurada

### load-env.py

Actualiza variables de entorno en archivos de configuración YAML para diferentes servicios y entornos.

**Características:**
- Actualiza variables en múltiples entornos y servicios
- Preserva la estructura y formato YAML
- Proporciona un resumen detallado de los cambios realizados

### create-prs.py

Crea y gestiona Pull Requests en GitHub.

**Características:**
- Verifica la instalación de GitHub CLI
- Lista PRs activos
- Revisa el estado de PRs
- Crea PRs para directorios específicos

### kube.py

Utilidad para interactuar con pods de Kubernetes.

**Comandos:**
- `logs`: Muestra logs de un pod
- `exec`: Conecta a un shell en un pod
- `image`: Obtiene la imagen utilizada por un pod
- `restart`: Reinicia pods y monitorea el nuevo pod

### utils.py

Módulo de utilidades comunes utilizado por otros scripts.

**Funciones:**
- `run_command`: Ejecuta comandos de shell con manejo de errores y captura de salida

## Uso

Cada script incluye su propia documentación y ayuda. Ejecuta cualquier script sin argumentos para ver las opciones disponibles.

```bash
python3 <script>.py
```

## Contribuciones

Para contribuir a este proyecto, por favor crea un fork del repositorio, realiza tus cambios y envía un Pull Request.