# Hugging Face 迁移复现包

私有仓库：[zhiyuanhucs/agent-benchmark-repro-20261022](https://huggingface.co/datasets/zhiyuanhucs/agent-benchmark-repro-20261022)。已验证版本：`8dbaaaf1d7e2a450c27492ccd1048bde77328bfe`。

包含 TB2.1（89）、Pro Verified（731）、DeepSWE（113）、SWRBench（1000）和 SWE-Review（500/462/422）的工作区源码、任务输入、固定配置、运行入口、评分工具和说明，共约 375 MB。TB2.1 原预制镜像通过固定 Hub 提交下载，合计约 21.6 GB，附逐归档 SHA-256 与 Docker image/layer 身份验证。

```bash
hf download zhiyuanhucs/agent-benchmark-repro-20261022 \
  --type dataset --revision 8dbaaaf1d7e2a450c27492ccd1048bde77328bfe \
  --local-dir benchmark-repro
```

新机器先按 HF README 安装 Python 3.12 独立环境、解包迁移，再配置模型/裁判 API。该包保留实际返回的 thinking，真实 API key 由主机转发进程从环境读取。

已完成 24 组配置生成与源码入口检查、任务覆盖与哈希检查、500 题离线评分数据读取、SSE thinking 和 gzip 转发测试。未在迁移目录重跑完整 benchmark。22 个实际负载文件的远端 Git/LFS 哈希及 README 下载校验已通过，详细证据见 [HF 上传核验](evidence/hf_benchmark_repro_upload_20261022.json)。
