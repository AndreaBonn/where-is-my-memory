import os
import subprocess
from pathlib import Path

import pytest

from wimm.config import Config
from wimm.model.snapshot import ProcessMember
from wimm.paths import UserPaths
from wimm.serialize import snapshot_from_json, snapshot_to_json
from wimm.service.sampler import Sampler, SamplerEnvironment, default_collectors


@pytest.mark.integration
def test_sampler_collects_a_process_created_by_test(tmp_path: Path) -> None:
    child = subprocess.Popen(args=["/usr/bin/env", "sleep", "30"])
    try:
        paths = UserPaths(config_dir=tmp_path, state_dir=tmp_path, cache_dir=tmp_path)
        environment = SamplerEnvironment(
            paths=paths, own_pid=os.getpid(), uid=os.getuid(), home=tmp_path
        )
        sampler = Sampler(
            collectors=default_collectors(environment=environment),
            environment=environment,
            config=Config(),
        )
        for _ in range(2):
            snapshot = sampler.run_cycle()
            assert snapshot_from_json(text=snapshot_to_json(snapshot=snapshot)) == snapshot
            assert snapshot.memory.total > 0
            assert snapshot.disk.total > 0
            members = [member for group in snapshot.groups for member in group.members]
            assert any(
                isinstance(member, ProcessMember) and member.pid == child.pid for member in members
            )
    finally:
        child.terminate()
        child.wait(timeout=5)
