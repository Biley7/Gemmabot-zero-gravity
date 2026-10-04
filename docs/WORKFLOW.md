# Workflow

## Branch Strategy

- `main`: Production-ready code
- `backend/<topic>`: Backend feature branches
- `frontend/<topic>`: Frontend feature branches

## Pull Request Process

1. Create a feature branch from `main`:
   - Backend: `backend/add-verifier`
   - Frontend: `frontend/improve-ui`

2. Make changes and commit frequently with small, focused commits

3. Push the branch and create a pull request into `main`

4. No direct pushes to `main` are allowed

5. After PR approval, merge into `main`

## Starting Work

1. Always pull the latest changes from `main` before starting work:
   ```bash
   git checkout main
   git pull
   git checkout -b backend/my-feature
   ```

2. Make small, atomic commits

3. Run tests before committing

4. Ensure the PR description clearly explains the change
