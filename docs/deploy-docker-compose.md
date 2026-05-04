# Deploy OPTIMAP with Docker Compose

OPTIMAP is containerised. The same Docker Compose recipe brings up the full stack — Django app, PostGIS database, and Nginx webserver — for both local use and production deployment. The two compose files are:

- [`docker-compose.yml`](../docker-compose.yml) — local / development.
- [`docker-compose.deploy.yml`](../docker-compose.deploy.yml) — production overrides (HTTPS via `certbot`).

This guide is for operators bringing up an instance. For configuration knobs see the [main README §Configuration](../README.md#configuration) and [`optimap/.env.example`](../optimap/.env.example). For day-to-day operation of a running instance see [docs/manage.md](manage.md).

## Bring up the stack

```bash
docker compose up

docker compose run --entrypoint python app manage.py loaddata fixtures/test_data.json
```

The database migrations are applied as part of the startup script, see [`etc/manage-and-run.sh`](../etc/manage-and-run.sh). You can still run the commands below manually if need be, e.g., during development.

```bash
docker compose run --entrypoint python app manage.py makemigrations # should not detect any changes, otherwise your local config might be outdated
docker compose run --entrypoint python app manage.py migrate
docker compose run --entrypoint python app manage.py collectstatic --noinput
```

Now open a browser at <http://localhost:80/>.

## Services overview

- **db**: Runs a PostgreSQL database with PostGIS extensions. Data is persisted in a Docker volume named `db_data`.
- **app**: The primary Django web application.
- **webserver**: An Nginx server for serving static files and test files.

## Ports

Not all of these ports are exposed by default, but they are available for local development — just uncomment the matching lines in the `docker-compose.yml` file.

- `5432`: Database (PostgreSQL/PostGIS)
- `8000`: App (Django server)
- `80`: Webserver (Nginx)

## Production deployment

The app is deployed in the TUD Enterprise Cloud. The HTTPS certificate is retrieved via `certbot`; see [`docker-compose.deploy.yml`](../docker-compose.deploy.yml) for the configuration and documentation links.
