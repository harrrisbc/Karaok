from engine.jobs import BusyError, JobRunner


def test_job_runner_rejects_second_submit():
    runner = JobRunner()
    gate = []

    def slow(job):
        import time

        job.step = "working"
        gate.append(1)
        while len(gate) < 2:
            time.sleep(0.01)
        job.step = "done-step"

    first = runner.submit("a", slow)
    assert runner.active() is first
    try:
        runner.submit("b", lambda job: None)
        raised = False
    except BusyError:
        raised = True
    assert raised
    gate.append(1)
    for _ in range(100):
        if first.status == "done":
            break
        import time

        time.sleep(0.02)
    assert first.status == "done"
    assert runner.active() is None
