# 专用 bwrap / AppArmor 管理员包

目的：让 ACS 使用严格 readonly filesystem 与独立 network namespace，解决
Ubuntu AppArmor userns capability 限制导致的 `RTM_NEWADDR: Operation not permitted`。
本包提供受控安装方案；目前仅完成无加载 parser 检查和安全门控单元测试，尚未加载策略或完成安装后验收。

## 已核对的来源和主机事实

- 上游固定 revision：`8e431ebcd915216a03ebc8d01e72b1741bb2f855`，
  [原始 profile](https://gitlab.com/apparmor/apparmor/-/raw/8e431ebcd915216a03ebc8d01e72b1741bb2f855/profiles/apparmor/profiles/extras/bwrap-userns-restrict)。
- 本包保留 `upstream-bwrap-userns-restrict`；SHA256：
  `634d3d3427c483f123cb5ed53b71ea13040187e07d9f67ca74421d42a6170f0e`。
- 衍生文件只替换精确 executable attachment 和 profile 标签，并移除两个可选
  local include，避免包外配置改变已审核策略。保留 ABI 4.0 与子进程叠加 capability 拒绝。
- 专用 profile SHA256：`7b2beb270c7218b549883337f53cbdca903d4e93803704af42788f63f93583a1`。
- 已在指定 Ubuntu 24.04 主机的 AppArmor parser 4.0.1 运行
  `--skip-kernel-load --skip-cache`，exit `0`，传输后 SHA 一致。没有写内核或缓存。
- 系统 helper 为 root-owned `/usr/bin/bwrap`，bubblewrap 0.9.0；审核 SHA256：
  `52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712`。
- [Ubuntu 官方说明](https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007)
  推荐专用 bwrap profile；[Codex 固定 launcher](https://github.com/openai/codex/blob/657a993cbee87acf52d14b758ce49dbd46d1b8eb/codex-rs/linux-sandbox/src/launcher.rs#L115)
  会选择显式 PATH 中具备所需能力的 system bwrap。

上游文件和衍生策略保留 AppArmor 上游许可归属，未重新许可上游内容。

## 精确管理范围

| 资源 | 要求 |
| --- | --- |
| `/opt/acs/codex-sandbox/bin/bwrap` | 源自已核验 helper；root owner；runtime group；0750；单链接 |
| `/etc/apparmor.d/acs-bwrap-userns` | root:root 0644；精确 profile SHA |
| `/opt/acs/codex-sandbox/manifest.json` | root:root 0600；记录本包身份、摘要、runtime uid/gid、创建的目录 |
| `acs_bwrap` / `acs_unpriv_bwrap` | 只由该 profile 装载的两个内核策略名 |

安装不修改 global sysctl、`/usr/bin/bwrap`、通用 AppArmor profile、服务或 Node 配置。
不会停止或重启无关服务。目标路径逐级用 directory fd/O_NOFOLLOW 校验；拒绝 symlink、
非 root owner、group/other writable 路径、已有外来文件和未由本包 manifest 证明的资源。
文件使用 link-if-absent 安装；不覆盖现有文件。仅 `--apply` 才允许 root 安装/卸载/验证动作。

## 管理员执行

将审核后的完整包放在**所有父目录及文件均由 root 拥有、不可被其他账户写入**的位置，
例如 `/root/acs-bwrap-package/`。不要从执行账户可写的 checkout 或 `/tmp` 路径运行 apply。
先核对随包 `SHA256SUMS`，并人工核对本 README 给出的上游/profile/helper 固定摘要。

```sh
cd /root/acs-bwrap-package
sha256sum -c SHA256SUMS
/usr/bin/python3 manage.py install --runtime-user changgeng --runtime-group changgeng
```

上述命令只检查，不创建目标文件、不加载或卸载策略。当前缺少的执行资源是具有
管理员权限的会话；现有免密 sudo 列表不覆盖本包的安装与 AppArmor 加载操作。

**管理员唯一需要执行的安装步骤：**

```sh
sudo /usr/bin/python3 /root/acs-bwrap-package/manage.py install --apply --runtime-user changgeng --runtime-group changgeng
```

等价入口为 `sh install.sh --apply ...`；不带 `--apply` 同样只检查。
安装先校验完整包、helper、路径与策略语法，写入本包 intent manifest 和精确文件，
再加载两个专用 profile，并立即进行实际后验验证。安装失败时只回滚本次新安装的已证明资源；
若发现存活/不可核验容量、资源被改写、内核卸载失败，会保留本包 manifest/profile 供管理员处理。
重复检查不会接管外来资源；重复 install 不会因为验证失败而删除调用前已有的本包安装。

## 安装后实际验证

安装步骤自动以指定的非 root uid/gid 执行宿主控制与 `bwrap`，清空附加组，使用同一显式环境。
fixture 在已验证的包目录下创建，不使用环境指定的临时目录。最外层和 input 目录始终由 root 拥有，
以 `0711` 允许 runtime UID 遍历但不能重命名目录或叶子；只有 `0600` 的 probe 文件属于 runtime UID。
这既使文件本身对测试 UID 可写，也避免把普通文件权限拒写误认为只读挂载。

root 在开放遍历权限前固定 parent/root/input/probe FD。此后的宿主 sentinel 校验只读取原 probe FD，
前后检查各级无 symlink 的 directory entry、inode、类型和元数据；读取上限为 64 字节，最多多读 1 字节判定超限。
发生 symlink、FIFO、文件/目录替换或文件持续增长时拒绝结果，不按 runtime 可改写的路径重新打开或无界读取。
以下三项必须全部通过：

1. 同 UID 的宿主进程实际写入控制字节、读回并恢复 sentinel，确认该用户具有写权限。
2. `--ro-bind` 正例运行完整验证器：写入必须被拒绝，并核对宿主 sentinel 保持原字节。
3. 只将同一个 synthetic input 的 `--ro-bind` 改成 `--bind`，其余参数和验证器完全相同。
   写入必须实际成功，宿主必须观察到控制字节；同一个 readonly 验证器必须以专用 exit `42` 失败。
   如果可写对照仍被 DAC 或其他限制拒写，整个安装后验证失败。

两种挂载都保留以下检查：

- 只挂载平台必要目录和 synthetic input，其他 synthetic source 不可见。
- input 可以读取；只读正例的宿主 sentinel 保持不变，可写负对照的控制字节必须回到宿主。
- `CapEff=0`、`CapPrm=0`，子进程 AppArmor label 必须恰含 `acs_bwrap` 和 `acs_unpriv_bwrap` 两个叠加 token，且 mode 为 `enforce`。
- network namespace 与主机不同，仅有 loopback，无非 loopback IPv4 路由。
- userns 两项 sysctl 仍为 `1`，包没有改变全局设置。

可写负对照只改变自动清理的 synthetic fixture，不使用任何真实 source 或凭据文件。
父进程不会以 root 身份重写已交给 runtime UID 的 fixture 路径。内核 profile 清单会保留 mode，
两个专用 profile 都必须报告 `enforce`；同名 `complain`、缺项或含糊结果不能作为安装后验收证据。
这是补齐配置与身份验证，不是已经证明其他模式存在 capability 绕过。

验证输出为 JSON，分别记录 `host_write_control`、`readonly_host_sentinel_preserved` 和
`writable_bind_control`。只有管理员实际运行三项控制后，结果才证明该专用 helper 的这些限制；
不代表 Codex 模型、多机或 Runtime Gate 已通过。本次 Windows 验证为 53 项 guard 测试通过，7 项 Linux 原生 FD 测试跳过；
随后以 Linux 非 root UID 运行同一套测试，60 项全部通过，包含 7 项实际 FD 替换/增长用例；Ruff 通过。
测试使用真实临时文件写入/恢复，UID、capability、namespace 和 readonly 拒写观察由测试注入，
不代表真实降 UID 或挂载测试。Linux 原生 FD 测试以普通测试 UID 运行，使用真实替换/增长和 5 秒子进程看门狗；
root owner admission 在这些用例中有明确替身，不能据此声明 root 部署已验收。
真实 root 安装及两种挂载对照仍为 `not_run`，需要独立复核后由管理员执行。
管理员成功后，Management 仍需在新的授权 Node profile 中将显式 PATH 前置为
`/opt/acs/codex-sandbox/bin:/usr/bin:/bin`，保持原 Codex named filesystem/network policy，
重新执行无模型 Driver spawn/inspect/resume 及后续独立 conformance。包不会自动改变 Node PATH。

## 卸载与回滚

先在 Node 层停止**本包路径/profile 的所有容量**并恢复该 Node 原来的 PATH。
脚本会再次扫描 executable 和 AppArmor label；有匹配进程或无法检查的用户进程时拒绝卸载，
不会杀进程。第一次确认停止后，暂时关闭 helper 的执行权限、再次扫描，防止普通账户新建容量。
卸载失败则恢复 helper 执行权限并保留尚需管理员处理的资源。

```sh
/usr/bin/python3 /root/acs-bwrap-package/manage.py uninstall
sudo /usr/bin/python3 /root/acs-bwrap-package/manage.py uninstall --apply --capacity-stopped
```

卸载只移除这两个专用 profile，以及字节、owner/mode、manifest 全部匹配的文件；
只 `rmdir` manifest 记录的空目录，不递归删除。系统 helper 后续升级、runtime 用户被移除，
均不应妨碍依据本包 manifest 卸载旧资源。内核 profile 卸载未确认时不会删除其策略文件。

兼容性风险集中在 bwrap 的 namespace 初始化权限和子进程 profile stacking；
必须保留后验 cap-drop/网络/readonly 检查。通用 bwrap profile 曾有其他应用回归，
本包使用专用路径和标签控制影响范围，并保留独立回滚入口。
