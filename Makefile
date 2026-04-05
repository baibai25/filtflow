format:
	uv run ruff format

build:
	powershell -ExecutionPolicy Bypass -File scripts\build.ps1
