# Muse BF16 API 恢复状态

状态：尚未恢复可用，当前阶段：waiting_backend_readiness

专用 Slurm 作业 3383；BF16 权重，16×H200，TP16/EP16；接入上限为全局 8 路同时生成，更多请求排队。该配置上限不是新一轮吞吐实测结果。

Base URL：`https://muse.zhiyuanllm.com/v1`；模型别名：`muse-spark-open` / `muse-spark-open-bf16`。

原三个客户端 key 不轮换；ready 前验证三把 key 的公网流式输出及未鉴权 401，thinking 和工具解析由 Muse parser 透传。

完整生成额外验证：尚未完成。
 
域名或 /v1/models 返回响应不能证明 GPU 模型已就绪。自动激活器在核对 allocation 归属、后端 BF16 配置和原三 key 的实际生成后才标记 active；allocation 结束后停用旧后端路由。

[机器可读状态](muse_api_status.json)；[部署代码与说明](../../deployment/muse-openai-api/README.zh-CN.md)。
