# FASE 22.5 — Soporte del grupo OESTE en discovery/ingesta

## Objetivo

Extender el discovery de Segunda FEB 2025-2026 al grupo **OESTE** (26 jornadas,
7 partidos/jornada) sin romper el grupo **ESTE**, usando solo stdlib (sin
Selenium/Playwright/requests), sin cookies/sesiones persistentes y sin imprimir
secretos.

## Hallazgo clave

El grupo OESTE **NO es alcanzable por URL GET**. Probadas múltiples variantes
(`?grupo=`, `?g=`, `?grupoId=`, `?group=`, `?fase=`, path `/calendario/segundafeb/3/2025`,
`/calendario/segundafeb/88880`, etc.) — todas devuelven ESTE o 404. La única vía
es un **POST ASP.NET** al formulario de `calendario.aspx`:

- El GET base (`calendario.aspx?g=2&t=2025&nm=segundafeb`) redirige (301) a
  `/calendario/segundafeb/2/2025` y devuelve el dropdown de grupos:
  - `<option value="88879">Liga Regular "ESTE"</option>` (seleccionado)
  - `<option value="88880">Liga Regular "OESTE"</option>`
- El POST reenvía los **hidden fields** de la página (`__VIEWSTATE`,
  `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, `_ctl0:token`) y el campo del
  dropdown con **nombres con dos puntos** (`_ctl0:MainContentPlaceHolderMaster:
  gruposDropDownList=88880`). Con `$` en vez de `:` el servidor responde HTTP 500.
- Se demostró que el POST mínimo (hidden fields + valor del dropdown, sin
  `__EVENTTARGET`/`__EVENTARGUMENT`/token) ya devuelve el calendario OESTE; el
  código incluye `__EVENTTARGET`/`__EVENTARGUMENT` por fidelidad sin depender de
  ellos. Sin cookies (urllib sin CookieJar), sin Selenium.

## Cambios

- `scripts/feb/discover_matches.py`
  - `SUPPORTED_GROUPS = ("ESTE", "OESTE")`.
  - `_hidden_inputs(html)` — extrae los hidden fields del formulario ASP.NET.
  - `_grupo_value(html, group)` — valor del dropdown para el grupo pedido
    (parsea `Liga Regular "OESTE"` → `88880`).
  - `_post_grupo(base_url, page_html, group)` — POST mínimo (hidden + dropdown,
    nombres con `:`) a la URL final (urljoin con el `action` del form); no
    guarda cookies, no loguea `_ctl0:token`.
  - `fetch_calendar_group(season_code, group="ESTE")` — ESTE = GET idéntico a
    FASE 22.1 (sin POST, backward compatible); OESTE = GET + POST.
  - `discover_matches` / `resolve_round_for_match` aceptan `group`.
  - CLI `--group {ESTE,OESTE}`.
- `scripts/feb/ingest_round.py` — `SUPPORTED_GROUPS` compartido; `run_round`
  pasa `group` a discovery; rechaza grupos no soportados con exit 2.
- `scripts/feb/ingest_season.py` — `discover_rounds` delega en
  `DM.fetch_calendar_group` (ESTE usa la misma ruta GET de siempre).
- `tests/ingestion/fixtures/calendario_oeste_2025_2026.html` — fixture
  controlado ASP.NET (dropdown + hidden fields + jornadas 1-2 reales de OESTE).
- `tests/ingestion/test_fase_225_oeste.py` — 24 tests offline.

## Tests (offline)

Nuevos: 24 (`test_fase_225_oeste.py`). Total suite: **628 passed** (604 + 24).
Cubren: parse OESTE (jornadas, external IDs, round_number, scheduled_at,
equipos, dedupe), `discover_matches --group OESTE`, backward compat ESTE,
grupo inválido → ConfigError, extracción de dropdown/hidden fields, POST
correcto (método, URL, body con `:`, `__EVENTTARGET`, token reenviado pero
**nunca impreso**), `fetch_calendar_group` ESTE sin POST / OESTE con POST,
`resolve_round_for_match` OESTE, dry-run y full de `ingest_round`/`ingest_season`
con group OESTE, CLI exit codes.

## Validación real (limitada)

1. Discovery OESTE jornada 1 → 7 partidos (2487759–2487765), equipos reales.
2. Calendario OESTE completo vía `fetch_calendar_group` → 26 jornadas, 182
   partidos únicos (2487759–2487940); ESTE sin cambios (jornada 26 →
   2487024–2487030).
3. Ingesta controlada de la **jornada 1 OESTE** a producción: `match_ok=7`,
   `stats_ok=7`, `failed=0`. Replay idempotente (7/7, 0 duplicados).
4. API: 2487759 y 2487765 devuelven `round_number=1`; 2486849 (ESTE) sigue en 1.
   No se ingirió la temporada OESTE completa (fuera de alcance).

## Seguridad

- `_ctl0:token` (JWT de la página FEB) se reenvía en el POST pero jamás se
  imprime ni se loguea (test dedicado).
- Sin cookies/sesiones persistentes; sin Selenium/Playwright/requests.
- No se imprimen `FEB_TOKEN`, `FEB_API_KEY` ni Authorization headers.

## Limitaciones

- OESTE depende del POST ASP.NET; si FEB cambia los nombres de los campos
  (colons→`$`) o el token del formulario, el discovery OESTE fallaría con
  `SourceError` (visible, no silencioso). ESTE no se ve afectado.
- El grupo se elige por el texto del dropdown (`Liga Regular "OESTE"`); si FEB
  renombra los grupos, `_grupo_value` devolvería None y fallaría de forma
  controlada.

## Próximo paso recomendado

Ingesta de la temporada OESTE completa (`ingest_season --group OESTE`) con el
mismo retry 429 y delay de ESTE (FASE 22.4), validando idempotencia y que los
`round_number`/`scheduled_at` de OESTE no colisionan con ESTE en la API.