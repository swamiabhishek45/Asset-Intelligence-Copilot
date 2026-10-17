param (
    [string]$Action = "up"
)

switch ($Action.ToLower()) {
    "up" {
        docker compose up -d
    }
    "down" {
        docker compose down
    }
    "reset" {
        docker compose down -v
        docker compose up -d
        Write-Host "Waiting for services to become healthy..."
        Start-Sleep -Seconds 10
        docker compose exec -T backend python -m backend.load_dataset
    }
    "logs" {
        docker compose logs -f
    }
    "test" {
        python scripts/e2e.py
    }
    default {
        Write-Host "Usage: .\scripts\compose.ps1 -Action [up|down|reset|logs|test]"
    }
}
