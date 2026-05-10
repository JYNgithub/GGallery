import reflex as rx

# Reflex runs on its own frontend and backend
# On default dev mode, frontend and backend uses different ports (can be defined using backend_port and frontend_port)
# On "--env prod" mode, both frontend and backend share the same port (defined in api_url)

config = rx.Config(
    app_name="frontend",
    api_url="http://localhost:3000",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ]
)