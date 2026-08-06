

# Sistema de Investigación Agéntica Enoch

![Enoch — plano de control de investigación con IA auditable](site/assets/readme-hero.png)

**Enoch es un plano de control para investigación autónoma con IA acotada.** Convierte la recepción de ideas, la ejecución de trabajadores, la captura de evidencias, los informes generados y las puertas de lanzamiento público en transiciones de estado explícitas, en lugar de confiar en que una sesión del modelo "probablemente terminó".

<p>
  <a href="https://solo-09d10f60.mintlify.app/"><strong>Documentación</strong></a> ·
  <a href="https://alias8818.github.io/enoch-agentic-research-system/"><strong>Sitio web</strong></a> ·
  <a href="https://github.com/alias8818/enoch-ai-research-corpus"><strong>Corpus de investigación</strong></a> ·
  <a href="https://github.com/alias8818/enoch-promising-signals"><strong>Señales prometedoras</strong></a>
</p>

![Flujo del plano de control](site/assets/control-plane-flow.svg)

## Postura actual de lanzamiento público

| Superficie | Dato público actual |
| --- | --- |
| Tiempo de ejecución | `1.41.94` |
| Artefactos del corpus | `393` artefactos de investigación generados por IA |
| Puerta de empaquetado/procedencia | `393/393` cumplidas |
| Auditoría estricta de afirmación/evidencia | `393/393` cumplidas |
| Señales prometedoras | `6,381` señales acotadas sin formato de artículo |

Esas cifras son datos de lanzamiento público, no afirmaciones de validez científica. Enoch hace visible la diferencia: la salud operativa, la preservación de señales, la preparación del corpus de artículos y la postura de confianza pública son afirmaciones separadas.

## Por qué existe esto

El trabajo autónomo con IA de larga duración falla de maneras que los scripts ordinarios no presentan:

- los procesos hijos pueden continuar después de que una sesión de agente parezca inactiva;
- la telemetría de los trabajadores puede discrepar con el estado de la cola;
- las filas obsoletas y los paneles optimistas pueden ocultar trabajos bloqueados;
- las evidencias se dispersan entre máquinas y carpetas de ejecución;
- los informes generados pueden exagerar los resultados cuando no se conservan los límites de las afirmaciones.

Enoch trata estos problemas como **problemas del plano de control**. El sistema mantiene el estado de la cola, la veracidad de los trabajadores, los controles de pausa/mantenimiento, la sincronización de evidencias, la generación de artefactos y las puertas de lanzamiento fuera de la conversación del modelo.

## Qué contiene este repositorio

- **Plano de control FastAPI** para el estado de la cola, el estado del proyecto, la automatización de publicaciones, los controles de pausa/mantenimiento y las decisiones de despacho.
- **Puerta de trabajadores y verificaciones previas** para la veracidad del árbol de procesos, ventanas de silencio de telemetría y límites de despacho seguros. El código/configuración antiguo aún puede decir `wake_gate`; trate eso como un nombre de compatibilidad.
- **Registros de la Instalación de Investigación** para el escaneo de fuentes, generación de candidatos, comparación de deduplicación/historial, puntuación de novedad/viabilidad y decisiones de admisión.
- **Panel V2** para la preparación orientada al operador, colas, ejecuciones, artículos y estado de la puerta de evidencia.
- **Sincronización de evidencias y escritor de artefactos** para notas de ejecución, métricas, resúmenes de resultados, paquetes de evidencia, registros de afirmaciones e informes generados.
- **Validadores de lanzamiento** para empaquetado/procedencia, auditoría estricta de afirmación/evidencia, conteos públicos y superficies públicas generadas.

## Estructura del sistema

```text
Research Facility source scan
  -> generated research candidates
  -> dedupe / score / admission ledger
  -> control-plane ideas workbench
  -> queue candidate
  -> control-plane dispatch gates
  -> worker preflight + worker gate
  -> agent run with process/telemetry supervision
  -> evidence sync
  -> AI-generated research artifact
  -> packaging/provenance + strict claim/evidence gates
  -> public corpus or promising-signal lane
```

Para los límites actuales de tiempo de ejecución, almacenamiento, trabajadores, artefactos de decisión, automatización y compatibilidad, consulte [`docs/current-runtime-snapshot.md`](docs/current-runtime-snapshot.md).

## Salidas públicas

- [`alias8818/enoch-ai-research-corpus`](https://github.com/alias8818/enoch-ai-research-corpus) contiene artefactos de investigación generados, paquetes de evidencia, registros de afirmaciones, manifiestos e informes de auditoría.
- [`alias8818/enoch-promising-signals`](https://github.com/alias8818/enoch-promising-signals) preserva resultados útiles acotados o bloqueados por escala computacional que no son artículos. Estos no son artículos ni resultados revisados por pares.
- [`aliasocracy/enoch-ai-research-corpus`](https://huggingface.co/datasets/aliasocracy/enoch-ai-research-corpus) es un espejo del conjunto de datos del corpus público y de la división de señales prometedoras.

Los informes producidos por las ejecuciones de Enoch son **artefactos de investigación generados por IA**, no artículos escritos por humanos ni revisados por pares. El mantenedor publica el corpus para su inspección y crítica, pero no reclama autoría personal de los artículos generados, los argumentos ni el prosa.

## Cómo empezar

Para una prueba rápida local de desarrollo, comience con [`docs/quickstart.md`](docs/quickstart.md).

Para una ruta de implementación completa, consulte [`docs/deployment-guide.md`](docs/deployment-guide.md). Para campos de configuración individuales, comience desde `config.example.json` y [`docs/configuration-reference.md`](docs/configuration-reference.md).

Nunca realice commit de archivos de configuración activos ni credenciales.

## Desarrollo

```bash
uv run pytest -q
python scripts/validate_versioning.py
python3 scripts/validate_runtime_snapshot_links.py
python3 scripts/validate_runtime_deploy.py --source . --runtime /opt/enoch-control-plane --expected-commit HEAD --summary-only
```

## Mapa de documentación

- [Hosted Enoch Docs](https://solo-09d10f60.mintlify.app/) — documentación para operadores y revisores ([fuente](https://github.com/alias8818/enoch-docs))
- [`docs/operator-runbook.md`](docs/operator-runbook.md) — preparación a largo plazo, pausa/reanudación, callbacks y verificaciones de puertas de artículos
- [`docs/research-facility.md`](docs/research-facility.md) — registros de fuente/candidato/admisión/linaje
- [`docs/release/authorship-and-provenance.md`](docs/release/authorship-and-provenance.md) — contextualización de artefactos generados
- [`CHANGELOG.md`](CHANGELOG.md) — historial de versiones de tiempo de ejecución y notas de compatibilidad

## Seguridad

Antes de publicar o implementar cambios, ejecute escaneos de secretos y pruebas. Consulte [`SECURITY.md`](SECURITY.md). La documentación e imágenes públicas no deben exponer nombres de host privados, rutas internas, tokens, estado activo del operador ni anclajes de conteo obsoletos.

## Licencia

Apache License 2.0. Consulte [`LICENSE`](LICENSE).
