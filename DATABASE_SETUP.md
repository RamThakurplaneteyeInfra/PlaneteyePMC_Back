# PostgreSQL setup (password: `root`)

Django is configured for:

| Setting   | Value      |
|----------|------------|
| Database | `pmc_db`   |
| User     | `postgres` |
| Password | `root`     |
| Host     | `localhost` |
| Port     | `5432`     |

## One-time setup

1. Install PostgreSQL and start the service.
2. Open **SQL Shell (psql)** or pgAdmin and run:

   ```sql
   ALTER USER postgres WITH PASSWORD 'root';
   CREATE DATABASE pmc_db;
   ```

   If `CREATE DATABASE` says the database already exists, that’s fine.

3. From the project folder:

   ```powershell
   cd C:\Users\planeteye01\Desktop\PMC\backend
   python manage.py migrate
   ```

That creates all Django tables in `pmc_db`.

## Override without editing code

```powershell
$env:DB_PASSWORD = "your_password"
$env:DB_NAME = "pmc_db"
python manage.py migrate
```

## Use SQLite instead (no PostgreSQL)

```powershell
$env:USE_POSTGRESQL = "false"
python manage.py migrate
```
