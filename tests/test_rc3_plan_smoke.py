from schemaledger.task_loop import run_prompt


def test_task_runtime_is_wired(fake_llm):
    from schemaledger.task_runtime import TaskRuntime

    run = run_prompt("What kind of anime is Macross?", runtime=TaskRuntime(llm=fake_llm))
    assert run.interpretation.resolved_subject == "Macross"
