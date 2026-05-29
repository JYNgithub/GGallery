# GGallery

<p align="center">
  <img src="frontend/assets/favicon_display.png" alt="GGallery" width="20%" />
</p>

A self-hosted media gallery for personal photo and video storage. Designed with a decoupled architecture for scalability and efficient large-file media streaming for fast and organized personal media management.

> **Note:** Full deployment documentation is still a work in progress. The app assumes you already have a PostgreSQL database and a [Garage](https://garagehq.deuxfleurs.fr/) S3-compatible object store running in your environment, accessible via SSH tunnel with the required credentials listed in a .env file.

## Features

<table>
  <tr>
    <td><img src="frontend/assets/showcase1.gif" alt="Showcase 1" /></td>
    <td><img src="frontend/assets/showcase2.gif" alt="Showcase 2" /></td>
  </tr>
</table>

- Photo and video upload with metadata extraction
- Video streaming 
- Optimized lazy-loaded gallery 
- Tagging and bulk selection
- Filtering by date range, tags, and media type
- SSH tunnel support for remote database and object storage

## Stack

| Layer | Technology |
|---|---|
| Frontend | Reflex |
| Backend | FastAPI |
| Database | PostgreSQL |
| Object Storage | Garage |

## Usage

```bash
docker compose up --build
```

## Upcoming

- Improved security updates
- Improved mobile experience

