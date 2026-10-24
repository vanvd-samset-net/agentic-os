"""Adapter theo loại agent. Thêm loại mới: viết module có hàm run(ctx) -> AdapterResult và khai báo ở đây."""
from . import claude_code, shell

REGISTRY = {"claude-code": claude_code.run, "shell": shell.run}
