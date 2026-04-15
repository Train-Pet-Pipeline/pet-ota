# pet-ota Design Spec

> OTA 差分更新、灰度分发、回滚。pipeline 链最后一环。

**Date:** 2026-04-15
**Status:** Approved
**Upstream:** pet-quantize (签名 tarball + manifest.json)

---

## 1. 架构总览

```
pet-quantize (签名 tarball + manifest.json)
    ↓
pet-ota/
├── src/pet_ota/
│   ├── config.py                  # Pydantic params loader + JSON logging
│   ├── backend/
│   │   ├── base.py                # OTABackend 抽象接口 (Protocol)
│   │   └── local.py               # LocalBackend — 文件系统实现
│   ├── packaging/
│   │   ├── make_delta.py          # bsdiff4 差分打包
│   │   ├── upload_artifact.py     # 上传制品到 backend
│   │   └── create_deployment.py   # 创建部署（指定设备组）
│   ├── release/
│   │   ├── check_gate.py          # 发布门控 (5 项检查)
│   │   ├── canary_rollout.py      # 5% → 48h → 100% 灰度逻辑
│   │   └── rollback.py            # 回滚到上一个已知好的版本
│   └── monitoring/
│       ├── check_update_rate.py   # 成功率统计
│       └── alert.py               # CRITICAL 日志告警
├── tests/
├── params.yaml
├── Makefile
└── pyproject.toml
```

**核心设计决策：**

- **OTABackend Protocol**: 统一接口，v1 用 `LocalBackend`（文件系统），未来接 Mender 只需加 `MenderBackend`
- **bsdiff4 纯 Python**: LoRA 权重 50-100MB，bsdiff4 性能足够，不依赖系统工具
- **JSON 文件持久化**: 部署状态存 JSON 文件（`deployments/`），数据量小、运维可直接查看
- **纯日志告警**: v1 告警只输出结构化 JSON 日志，不做通知基础设施
- **门控值注入**: v1 通过 params.yaml `gate_overrides` 传入门控检查值，跨仓库 gate 是 CI 层面的事

---

## 2. OTABackend 抽象接口

```python
class OTABackend(Protocol):
    """OTA 后端统一接口。"""

    def upload_artifact(self, artifact_path: str, version: str) -> str:
        """上传制品，返回 artifact_id。"""

    def list_device_groups(self) -> list[str]:
        """列出所有设备组。"""

    def create_deployment(self, artifact_id: str, device_group: str, name: str) -> str:
        """创建部署，返回 deployment_id。"""

    def get_deployment_status(self, deployment_id: str) -> DeploymentStatus:
        """查询部署状态（成功数/失败数/待更新数）。"""

    def abort_deployment(self, deployment_id: str) -> None:
        """终止部署（用于回滚）。"""

    def get_device_update_history(self, device_group: str) -> list[dict]:
        """查询设备组的更新历史。"""
```

**DeploymentStatus** 数据类：

```python
@dataclass(frozen=True)
class DeploymentStatus:
    deployment_id: str
    version: str
    device_group: str
    status: str  # "deploying" | "observing" | "done" | "aborted"
    total_devices: int
    success_count: int
    failure_count: int
    pending_count: int
    created_at: str
    updated_at: str
```

---

## 3. LocalBackend 文件结构

```
artifacts/
├── store/                        # 上传的制品
│   └── v1.2.0/
│       ├── pet-model-v1.2.0.tar.gz
│       └── manifest.json
│       └── delta-v1.1.0-to-v1.2.0.patch  # 差分包（可选）
deployments/
├── v1.2.0-canary.json           # 部署状态记录
└── v1.2.0-full.json
device_groups/
├── canary.json                   # ["device_001", "device_002"]
└── production.json               # ["device_001", ..., "device_040"]
```

每个 deployment JSON：

```json
{
  "deployment_id": "v1.2.0-canary-20260415",
  "version": "1.2.0",
  "device_group": "canary",
  "status": "done",
  "created_at": "2026-04-15T10:00:00Z",
  "updated_at": "2026-04-15T10:05:00Z",
  "devices": {
    "device_001": "success",
    "device_002": "success"
  }
}
```

---

## 4. 模块职责

### 4.1 packaging/

| 文件 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `make_delta.py` | 旧版 tarball + 新版 tarball | delta patch 文件 | bsdiff4 差分，记录 from_version → to_version |
| `upload_artifact.py` | tarball 路径 + version | artifact_id | 调 `pet_quantize.packaging.verify_package` 校验签名后上传到 backend |
| `create_deployment.py` | artifact_id + device_group | deployment_id | 调 backend.create_deployment，不硬编码设备 ID |

### 4.2 release/

| 文件 | 职责 |
|------|------|
| `check_gate.py` | 5 项门控检查：eval_passed, dpo_pairs ≥ 500, days_since_last_release ≥ 7, open_p0_bugs == 0, canary_group_ready。v1 从 params.yaml 的 `gate_overrides` 读值。返回 `(passed: bool, failures: list[str])` |
| `canary_rollout.py` | 灰度发布状态机（见第 5 节）。编排完整发布流程 |
| `rollback.py` | 终止当前部署 + 将设备组回退到上一个成功版本。记录回滚原因到 deployment JSON |

### 4.3 monitoring/

| 文件 | 职责 |
|------|------|
| `check_update_rate.py` | 从 backend 查询部署状态，计算成功率/失败率/待更新率，返回结构化结果 |
| `alert.py` | 失败率超阈值时输出 `CRITICAL` 级别结构化 JSON 日志 |

---

## 5. 灰度发布状态机

```
GATE_CHECK → CANARY_DEPLOYING → CANARY_OBSERVING → FULL_DEPLOYING → DONE
     ↓              ↓                  ↓                  ↓
   FAILED      ROLLING_BACK      ROLLING_BACK        ROLLING_BACK
                    ↓                  ↓                  ↓
                 ROLLED_BACK       ROLLED_BACK        ROLLED_BACK
```

- **GATE_CHECK**: 调 check_gate，任一项失败 → FAILED（不创建部署）
- **CANARY_DEPLOYING**: 向 canary 设备组（5%）推送，等待全部设备响应
- **CANARY_OBSERVING**: 观察期内轮询 check_update_rate，失败率超阈值 → ROLLING_BACK
- **FULL_DEPLOYING**: 向 production 设备组推送全量
- **ROLLING_BACK**: 调 rollback.py 终止部署，恢复上一版本
- 每次状态变更都持久化到 `deployments/<version>.json`

---

## 6. 错误处理

- 外部调用（verify_package、bsdiff4）失败：tenacity 重试 3 次，仍失败则记录错误并终止
- 部署过程中 backend 不可达：不静默失败，抛异常让调用方决定
- 回滚本身失败：`CRITICAL` 日志 + 状态标记为 `ROLLBACK_FAILED`（需人工介入）
- 所有错误输出结构化 JSON 日志，不允许空 except 或静默失败

---

## 7. 测试策略

- 全部用 `LocalBackend` + 真实文件操作，**不 mock**
- `make_delta` 测试：创建两个真实小文件，差分 → 合并 → 比较一致性
- `canary_rollout` 测试：通过 params.yaml 注入观察时间为 0 秒，跑完整状态机
- `check_gate` 测试：通过 gate_overrides 控制通过/失败两种路径
- `rollback` 测试：先创建一个成功部署，再触发回滚，验证状态回退
- `check_update_rate` 测试：创建真实 deployment JSON，验证成功率计算
- `alert` 测试：超阈值时验证日志输出包含 CRITICAL 级别

---

## 8. params.yaml 配置

```yaml
release:
  canary_percentage: 5
  canary_observe_hours: 48
  rollback_timeout_minutes: 5
  failure_rate_threshold: 0.10

gate_overrides:
  eval_passed: true
  dpo_pairs: 600
  days_since_last_release: 10
  open_p0_bugs: 0
  canary_group_ready: true

packaging:
  delta_enabled: true
  artifact_store_dir: "artifacts/store"
  public_key_path: ""

monitoring:
  poll_interval_seconds: 30
  alert_failure_threshold: 0.10

device_groups:
  canary: "device_groups/canary.json"
  production: "device_groups/production.json"

wandb:
  project: "pet-ota"
  entity: ""
```

---

## 9. 与 DEVELOPMENT_GUIDE 的偏差

| DEVELOPMENT_GUIDE | 实际设计 | 原因 |
|---|---|---|
| `make_delta.sh` (bsdiff) | `make_delta.py` (bsdiff4) | 纯 Python，无系统依赖，测试友好 |
| `server/` (docker-compose + Mender) | `backend/` (Protocol + LocalBackend) | v1 不需要 Mender 实例，抽象接口保留未来对接 |
| `mender.env`, `nginx.conf` | 不在 v1 范围 | 真实 Mender 部署时再加 |
| 门控直接查外部数据源 | `gate_overrides` 注入 | 跨仓库 gate 是 CI 层面的事 |

→ Task 最后一步需同步 DEVELOPMENT_GUIDE。
