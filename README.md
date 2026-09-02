# FEB SCORE

**Plataforma de datos deportivos para las competiciones de la Federación Española de Baloncesto (FEB).**

Un *core engine* de datos —ingesta, normalización, dominio, estadísticas y
analítica— diseñado para alimentar múltiples consumidores (API, web, app,
dashboards, redes, modelos de ML), no un scraper puntual. La referencia
funcional son productos como SofaScore, FotMob o Flashscore, centrado
inicialmente en la Segunda FEB.

```text
FUENTES → INGESTA → NORMALIZACIÓN → CORE DOMAIN → ESTADÍSTICAS → ANALYTICS → CONSUMIDORES
```

## Arquitectura

Diseño **Domain-Driven Design** con capas separadas y dependencias hacia el
dominio, contratos de eventos/comandos versionados y frontera HTTP fina.

```
src/feb_score/
  domain/           reglas y modelo de negocio (45 módulos, sin dependencias externas)
  application/      casos de uso, orquestación, puertos (27 módulos)
  infrastructure/   adaptadores: PostgreSQL, ingesta, rendering, repos (62 módulos)
  api/              frontera HTTP (FastAPI): analytics, exploración, contenido, auth
  server.py         arranque, migraciones, health/ready
contracts/          esquemas JSON Schema (Draft 2020-12) de comandos y eventos, versionados
tests/              153 archivos de test (dominio, aplicación, integración, producción)
docs/ARCHITECTURE.md
bounded_context_map.md · contract_matrix.md · contract_versioning.md
```

Puntos de diseño destacados:

- **Contratos versionados** (`contracts/commands`, `contracts/events`) con `$id` y
  `meta.version`, validados con JSON Schema — el límite entre productores y
  consumidores es explícito y testeable.
- **Idempotencia** en la ingesta (ver `validation_examples/idempotency_example.json`).
- **Bounded contexts** documentados en `bounded_context_map.md`.
- **Frontera HTTP** con endpoints de salud (`/health`, `/ready`), auth por API key,
  y `/docs` deshabilitable en producción.

## Stack

- **Python 3.11**
- **FastAPI** + **Uvicorn** (frontera HTTP)
- **PostgreSQL** vía `psycopg` (SQLite como backend local de desarrollo)
- **jsonschema** (validación de contratos)
- **Docker** multi-stage (imagen no-root, reproducible)
- **Railway** (despliegue) + **GitHub Actions** (CI/CD)

## Arrancar en local

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # ajustar variables
uvicorn feb_score.server:app --reload --app-dir src
```

Con Docker:

```bash
docker compose up --build
```

## Tests

```bash
python3 -m pytest -q
python3 -m pytest --cov=feb_score --cov-report=term -q   # con cobertura
```

## Estructura del repositorio

| Carpeta | Contenido |
|---|---|
| `src/feb_score/` | El motor: dominio, aplicación, infraestructura, API |
| `contracts/` | Esquemas versionados de comandos y eventos |
| `tests/` | Suite de tests (unitarios, integración, producción) |
| `docs/` | Documentación de arquitectura |
| `scripts/` | Utilidades y validadores de temporada |
| `.github/` | Pipelines de CI/CD |

## Estado

Proyecto en desarrollo activo. Núcleo de dominio, API y despliegue en
producción operativos; conector de fuente FEB entregado. La ingesta de datos
oficiales en tiempo real queda supeditada a credenciales de la fuente.
