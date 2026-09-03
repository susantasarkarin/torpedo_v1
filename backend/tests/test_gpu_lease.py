"""
GPU lease lifecycle — mostly teardown.

Every test here exists because the corresponding failure costs $35/hour
until a human notices. Provisioning bugs are loud; teardown bugs are silent,
so that is where the coverage goes.
"""

import time

import pytest

from infra import gpu_lease as gl


class FakeDriver:
    """Records calls; never touches the network."""

    def __init__(self, pods=None, fail_terminate_times=0, fail_create=False):
        self.pods = list(pods or [])
        self.created = []
        self.terminated = []
        self._fail_terminate_times = fail_terminate_times
        self._fail_create = fail_create

    def create_pod(self, name, image, gpu_type, gpu_count, env, args,
                   disk_gb, volume_gb):
        if self._fail_create:
            raise gl.GpuLeaseError("no capacity")
        pod_id = f"pod-{len(self.created)}"
        self.created.append({"id": pod_id, "name": name, "env": env,
                             "args": args, "gpuCount": gpu_count})
        return pod_id

    def list_pods(self):
        return self.pods

    def terminate_pod(self, pod_id):
        if self._fail_terminate_times > 0:
            self._fail_terminate_times -= 1
            raise gl.GpuLeaseError("provider 503")
        self.terminated.append(pod_id)


@pytest.fixture(autouse=True)
def _no_sleep_no_wait(monkeypatch):
    """Tests must not actually sleep through backoff or cold start."""
    monkeypatch.setattr(gl.time, "sleep", lambda *_: None)
    monkeypatch.setattr(gl, "wait_for_ready", lambda *a, **k: None)


# ---------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------

def test_pod_is_destroyed_on_success():
    driver = FakeDriver()
    with gl.lease_gpu(driver=driver, reap_first=False) as lease:
        assert lease.pod_id == "pod-0"
    assert driver.terminated == ["pod-0"]


def test_pod_is_destroyed_when_the_body_raises():
    """The expensive case: the job blows up and nobody tidies the node."""
    driver = FakeDriver()
    with pytest.raises(ValueError):
        with gl.lease_gpu(driver=driver, reap_first=False):
            raise ValueError("batch exploded")
    assert driver.terminated == ["pod-0"]


def test_pod_is_destroyed_on_keyboard_interrupt():
    driver = FakeDriver()
    with pytest.raises(KeyboardInterrupt):
        with gl.lease_gpu(driver=driver, reap_first=False):
            raise KeyboardInterrupt
    assert driver.terminated == ["pod-0"]


def test_teardown_retries_transient_failures():
    driver = FakeDriver(fail_terminate_times=2)
    with gl.lease_gpu(driver=driver, reap_first=False):
        pass
    assert driver.terminated == ["pod-0"]


def test_teardown_failure_raises_loudly():
    """A pod that will not die must never be logged and forgotten."""
    driver = FakeDriver(fail_terminate_times=99)
    with pytest.raises(gl.TeardownError) as exc:
        with gl.lease_gpu(driver=driver, reap_first=False):
            pass
    assert "still billing" in str(exc.value)
    assert "pod-0" in str(exc.value)


# ---------------------------------------------------------------
# Orphan reaping — the layer that survives the launcher dying
# ---------------------------------------------------------------

def _pod(pod_id, name, age_minutes):
    created = time.gmtime(time.time() - age_minutes * 60)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", created)
    return {"id": pod_id, "name": name, "createdAt": stamp}


def test_reap_destroys_only_stale_pods():
    driver = FakeDriver(pods=[
        _pod("old", f"{gl.POD_NAME_PREFIX}-aaa", 300),
        _pod("young", f"{gl.POD_NAME_PREFIX}-bbb", 5),
    ])
    reaped = gl.reap_orphans(max_age_minutes=120, driver=driver)
    assert reaped == ["old"]
    assert driver.terminated == ["old"]


def test_reap_never_touches_foreign_pods():
    """A stray reaper must not be able to destroy someone else's work."""
    driver = FakeDriver(pods=[
        _pod("theirs", "someone-elses-training-run", 5000),
        _pod("ours", f"{gl.POD_NAME_PREFIX}-ccc", 5000),
    ])
    reaped = gl.reap_orphans(max_age_minutes=60, driver=driver)
    assert reaped == ["ours"]
    assert "theirs" not in driver.terminated


def test_reap_skips_pods_with_unreadable_age():
    """Unknown age means unknown intent — leave it for a human."""
    driver = FakeDriver(pods=[{"id": "x", "name": f"{gl.POD_NAME_PREFIX}-d"}])
    assert gl.reap_orphans(max_age_minutes=1, driver=driver) == []
    assert driver.terminated == []


def test_reap_dry_run_destroys_nothing():
    driver = FakeDriver(pods=[_pod("old", f"{gl.POD_NAME_PREFIX}-e", 999)])
    assert gl.reap_orphans(max_age_minutes=1, dry_run=True, driver=driver) == ["old"]
    assert driver.terminated == []


def test_failed_reap_does_not_block_the_job():
    """A provider hiccup during the sweep must not cancel real work."""
    class BadList(FakeDriver):
        def list_pods(self):
            raise gl.GpuLeaseError("list failed")

    driver = BadList()
    with gl.lease_gpu(driver=driver, reap_first=True) as lease:
        assert lease.pod_id == "pod-0"
    assert driver.terminated == ["pod-0"]


# ---------------------------------------------------------------
# What we actually launch
# ---------------------------------------------------------------

def test_vllm_command_disables_thinking_and_requires_auth():
    cmd = gl._vllm_command("zai-org/GLM-5.2", "GLM-5.2", 8, 131072)
    assert '"enable_thinking": false' in cmd
    assert "--api-key $VLLM_API_KEY" in cmd
    assert "--tensor-parallel-size 8" in cmd


def test_each_lease_gets_a_distinct_secret():
    driver = FakeDriver()
    keys = []
    for _ in range(2):
        with gl.lease_gpu(driver=driver, reap_first=False) as lease:
            keys.append(lease.api_key)
    assert keys[0] != keys[1]
    assert len(keys[0]) > 20


def test_create_failure_leaves_nothing_running():
    driver = FakeDriver(fail_create=True)
    with pytest.raises(gl.GpuLeaseError):
        with gl.lease_gpu(driver=driver, reap_first=False):
            pass
    assert driver.terminated == []


def test_missing_api_key_refuses_to_provision(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(gl.GpuLeaseError) as exc:
        gl.api_key()
    assert "RUNPOD_API_KEY" in str(exc.value)
