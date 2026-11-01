# RAG 问答评估报告（阶段七）

- 生成时间：2026-10-31 06:38:46 UTC
- 评估集：data\eval\rag_questions.jsonl（76 题）
- 运行方式：服务层直调（不经过 HTTP）；LLM provider=**openai**，Embedding provider=**openai**（deepseek-chat）
- 拒答阈值：kb_refusal_min_score=0.10（2026-10-31 mock 语料校准，见 config.py）

## 分类型结果

| 类型 | 题数 | 通过 | 通过率 | 异常 | 平均延迟(ms) |
|---|---|---|---|---|---|
| kb | 51 | 47 | 92.2% | 0 | 1313.1 |
| no_basis | 10 | 8 | 80.0% | 0 | 486.1 |
| induce | 5 | 5 | 100.0% | 0 | 1385.8 |
| insufficient | 5 | 5 | 100.0% | 0 | 900.4 |
| needs_db | 3 | 3 | 100.0% | 0 | 8.7 |
| fallback_other | 2 | 2 | 100.0% | 0 | 166.6 |

**总览**：76 题，异常 0（错误率 0.0%），端到端平均延迟 1100.2 ms

## 未通过明细（含拒答题与异常题）

| id | 类型 | 问题 | answer_type | 说明 |
|---|---|---|---|---|
| 34 | kb | 去哪里维修？ | fallback | answer_type=fallback（预期外） |
| 37 | kb | 怎么申请开发票？ | fallback | answer_type=fallback（预期外） |
| 45 | kb | 地址填错了怎么办？ | fallback | answer_type=fallback（预期外） |
| 52 | kb | POLICY-2026-01 对应什么政策？ | fallback | answer_type=fallback（预期外） |
| 105 | no_basis | 可以加急配送吗 | generated | answer_type=generated（预期外） |
| 106 | no_basis | 支持货到付款吗 | generated | answer_type=generated（预期外） |

## 评估方法与局限（必读）

- **管线口径**：当前 LLM 与 Embedding 均为 mock，结果验证的是 上下文组装、引用机制、拒答机制与降级路径的**正确性**，
  不代表真实 DeepSeek 生成质量与真实 BGE-M3 检索质量；
- **引用真实性检查**：回答中 [N] 编号必须存在于返回来源（7.3 要求）， mock 下引用由上下文构造，真实模型接入后该检查是防幻觉的关键闸门；
- **拒答局限（如实声明）**：mock 词袋向量下，无依据题与有依据题的相似度 区间重叠（校准数据见 config.py），10 道无依据题仅部分被拒答； 接入真实 BGE-M3 后语义差距拉开，需用同一评估集重新校准阈值并复核；
- **诱导防护**：提示词层约束 + mock 构造性通过；真实模型下需抽样人工复核， 后续可引入 LLM 评审（需记录评审方法并人工抽检）；
- 正确性/忠实性在 mock 下由构造保证，真实模型下应使用 LLM 裁判 + 人工抽检 的评估方案（本报告不含主观判断）。
