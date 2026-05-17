"""RunContext and helpers."""

class RunContext:
    def __init__(self, run_id: str, logger=None, metrics=None, db_conn=None):
        self.run_id = run_id
        self.logger = logger
        self.metrics = metrics
        self.db_conn = db_conn
