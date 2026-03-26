from __future__ import annotations

from flask import Flask, abort, jsonify, render_template

from .repository import TaskBrowseRepository


def create_app(repository: TaskBrowseRepository) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    @app.get("/tasks")
    def tasks_page() -> object:
        return render_template("task_list.html", tasks=repository.list_tasks())

    @app.get("/tasks/<task_id>")
    def task_trace_page(task_id: str) -> object:
        try:
            trace = repository.get_task_trace(task_id)
        except KeyError:
            abort(404)
        return render_template("task_trace.html", trace=trace)

    @app.get("/api/tasks")
    def list_tasks() -> object:
        return jsonify(repository.list_tasks())

    @app.get("/api/tasks/<task_id>")
    def get_task(task_id: str) -> object:
        try:
            return jsonify(repository.get_task(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/coverage")
    def get_task_coverage(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_coverage(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/schema")
    def get_task_schema(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_schema(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/events")
    def get_task_events(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_events(task_id))
        except KeyError:
            abort(404)

    @app.get("/api/tasks/<task_id>/trace")
    def get_task_trace(task_id: str) -> object:
        try:
            return jsonify(repository.get_task_trace(task_id))
        except KeyError:
            abort(404)

    return app
