import reflex as rx

# Reflex runs on its own frontend and backend, api_url expects the Reflex's backend url
# On default dev mode, frontend and backend uses different ports (can be defined using backend_port and frontend_port)
# On "--env prod" mode, both frontend and backend share the same port (defined in api_url)
# Note switch between port 3000 (for prod) and 8001 (for dev)

config = rx.Config(
    app_name="frontend",
    api_url="http://localhost:3000",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ]
)