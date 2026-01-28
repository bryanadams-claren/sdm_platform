# Front-End Development Details

## Test Credentials

### Django Admin Superuser
- **Email:** claude@testemail.com
- **Password:** robotsrule123
- **Admin URL:** http://localhost:8001/claren-manage/

## Local Development URLs

- **Main site:** http://localhost:8001
- **Homepage:** http://localhost:8001/home/
- **Back Pain Journey:** http://backpain.localhost:8001

## Notes

- The Django admin is at `/claren-manage/` (not the default `/admin/`)
- Subdomains are used for different journeys (e.g., `backpain.localhost:8001`)
- Django Debug Toolbar is enabled in local development
- `MEDIA_ROOT` is set in `.envs/.local/.django` to point to `C:\Users\Bryan\code\sdm_platform\sdm_platform\media` so that uploads are shared with the Celery worker running from the `sdm_platform` project
