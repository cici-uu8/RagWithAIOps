from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_separate_full_demo_command_files_exist_and_enable_aiops_lab():
    start_command = read_text("启动企业助手&数据库.command")
    stop_command = read_text("停止企业助手&数据库.command")

    assert "INCLUDE_AIOPS_LAB=1" in start_command
    assert "scripts/launcher/start_enterprise_assistant.sh" in start_command
    assert "INCLUDE_AIOPS_LAB=1" in stop_command
    assert "scripts/launcher/stop_enterprise_assistant.sh" in stop_command


def test_default_command_files_stay_main_app_only():
    start_command = read_text("启动企业助手.command")
    stop_command = read_text("停止企业助手.command")

    assert "INCLUDE_AIOPS_LAB=1" not in start_command
    assert "INCLUDE_AIOPS_LAB=1" not in stop_command


def test_launcher_scripts_support_optional_aiops_lab_without_fault_injection():
    start_script = read_text("scripts/launcher/start_enterprise_assistant.sh")
    stop_script = read_text("scripts/launcher/stop_enterprise_assistant.sh")

    assert "INCLUDE_AIOPS_LAB" in start_script
    assert "docker compose -f aiops_lab/docker-compose.yml up --build -d" in start_script
    assert "aiops_lab/cmdb/seed.py" in start_script
    assert "http://localhost:9101/health" in start_script
    assert "http://localhost:9090/-/ready" in start_script
    assert "http://localhost:9093/-/ready" in start_script
    assert 'export AIOPS_PROMETHEUS_URL="http://localhost:9090"' in start_script
    assert 'export AIOPS_ALERTMANAGER_URL="http://localhost:9093"' in start_script
    assert 'export AIOPS_LOGS_DIR="aiops_lab/logs"' in start_script
    assert 'export AIOPS_CMDB_SQLITE_PATH="aiops_lab/cmdb/aiops_context.db"' in start_script
    assert "inject_fault.py" not in start_script
    assert "smoke_aiops.py" not in start_script

    assert "INCLUDE_AIOPS_LAB" in stop_script
    assert "docker compose -f aiops_lab/docker-compose.yml down" in stop_script
