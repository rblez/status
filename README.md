# Tiendly Status — status.tiendly.lat

Estado en vivo de los servicios de Tiendly (web, app y API). Sitio estático, sin base de datos ni login: solo HTML + JSON.

## Cómo funciona

- **`index.html`** — la página. Lee `status.json` e `incidents.json` y los muestra. Se actualiza sola cada 60 segundos. Si el JSON no carga, muestra el último estado conocido, nunca una página en blanco.
- **`scripts/monitor.py`** — hace ping a los 3 servicios (web, app, API) y actualiza `status.json` (estado actual, tiempo de respuesta, historial de los últimos 90 chequeos, uptime de 30 días) e `incidents.json` (abre un incidente cuando un servicio cae y lo cierra cuando vuelve, con duración). Clasifica cada servicio en `ok` / `slow` (más de 2000 ms) / `down`, y el estado general en `operational` / `degraded` / `partial` / `major`.
- **`.github/workflows/monitor.yml`** — corre el monitor cada 5 minutos desde GitHub Actions y commitea los JSON si cambiaron. El commit dispara el deploy en Cloudflare Pages.

## Conectar a Cloudflare Pages

1. En Cloudflare, crea un proyecto Pages nuevo desde este repo (`tiendly/status`), rama `main`, sin comando de build y sin directorio de salida (el sitio es estático, la raíz es la salida).
2. En el proyecto, añade el dominio personalizado `status.tiendly.lat`.
3. Listo: cada vez que el monitor actualiza los JSON, Pages redespliega solo.

La página no redirige a `/status` ni depende de Supabase: si www o Supabase se caen, la página sigue mostrando el último estado conocido.
