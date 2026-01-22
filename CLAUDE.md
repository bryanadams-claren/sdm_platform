   # Project-Specific Instructions for Claude Code

   ## Django-Specific
   - This is a Django project, started using Django Cookiecutter, using django-allauth for authentication, celery for background tasks, and django-celery-beat for scheduling tasks (and Redis as the broker)
   - Imports inside Celery tasks are intentional (circular import avoidance)
   - The database is PostgreSQL, and the project uses django-environ for environment variable management (with local environment variables in `.envs\.local`)
   - The production environment is AWS with Elastic Beanstalk for deploying the web (see `.elasticbeanstalk` and `.ebextensions` for web and worker configurations), with RDS for the database, SES for email, and S3 for file storage
   - The EB environment only deploys from git, so code changes must be committed to git before deploying to EB
   - The local environment is Windows, so please use powershell instead of bash

   ## Key architecture and apps
   - The goal of the project is to enable shared decision making with patients
   - `sdm_platform\llmchat` houses the machinery for managing the LLM, specifically using the langchain library (n.b., there is an MCP server installed for langchain documentation)
   - `sdm_platform\memory` houses the langmem-based memory system for analyzing the conversations, determining if the conversation is addressing the "conversation points," and summarizing the conversation
   - `sdm_platform\journeys` manages the configuration of a particular SDM journey (such as "backpain" or "kneepain")
   - `sdm_platform\evidence` uses ChromaDB to store a vector database of evidence to perform RAG (Retrieval-Augmented Generation) on patient queries over medical evidence literature
   - `sdm_platform\users` houses the user management system for managing patient and provider accounts

   ## Python Environment
   - Always use `uv run` to execute Python commands (e.g., `uv run python`, `uv run pytest`)

   ## Code Quality
   - Follow ruff linting rules strictly
   - Run linter before committing: `uv run ruff check <files>`
   - Line length limit is 88 characters
   - Add noqa comments only when absolutely necessary with explanation

   ## Testing
   - Run tests with: `uv run python manage.py test <test_path> --keepdb`
   - Always run tests after making changes to verify nothing broke
   - Write tests for new features and update tests when making changes
