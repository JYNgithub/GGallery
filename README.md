# GGallery

A self-hosted media gallery for personal photo and video storage. Designed with a decoupled architecture for scalability and efficient large-file media streaming for fast and organized personal media management.

> **Note:** Full deployment documentation is still a work in progress. The app assumes you already have a PostgreSQL database and a [Garage](https://garagehq.deuxfleurs.fr/) S3-compatible object store running in your environment, accessible via SSH tunnel with the required credentials listed in a .env file.

## Features

- Photo and video upload with metadata extraction
- Video streaming 
- Optimized lazy-loaded gallery 
- Tagging and bulk selection
- Filtering by date range, tags, and media type
- SSH tunnel support for remote database and object storage

## Upcoming

- Security updates
- Improved mobile experience

## Stack

| Layer | Technology |
|---|---|
| Frontend | Reflex (Python → React) |
| Backend | FastAPI |
| Database | PostgreSQL |
| Object Storage | Garage (S3-compatible) |

## Usage

```bash
docker compose up --build
```

## Disclaimer
  
> This project started as a personal project and was for learning purposes. I am aware there are more mature self-hosted media storage solutions out there.
