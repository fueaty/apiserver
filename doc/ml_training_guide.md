# 机器学习模型训练与部署指南

本文档介绍如何在Windows环境下训练内容匹配模型，并将其部署到Linux生产环境中使用。

## 1. Windows环境准备

### 1.1 安装必要软件
```bash
# 安装Python（建议3.8+）
# 从 https://www.python.org/downloads/ 下载并安装

# 安装必要库
pip install pandas scikit-learn joblib jieba numpy
```

### 1.2 准备训练数据
训练数据可以从生产环境中导出：
```bash
# 在Linux生产环境中导出数据
cd /root/apiserver
python3 export_all_headlines.py
```

将生成的 `all_headlines_data.json` 文件复制到Windows环境。

## 2. 模型训练

### 2.1 修改训练脚本
根据实际需求调整 [train_content_matching_model.py](file:///root/apiserver/train_content_matching_model.py) 中的参数和逻辑。

### 2.2 运行训练
```bash
python train_content_matching_model.py
```

训练完成后会生成以下文件：
- `content_matching_model.pkl` - 训练好的模型
- `platform_preferences.pkl` - 平台偏好配置

## 3. 模型部署

### 3.1 将模型文件复制到生产环境
```bash
# 使用SCP或其他方式将模型文件复制到生产服务器
scp content_matching_model.pkl platform_preferences.pkl user@server:/root/apiserver/
```

### 3.2 在生产环境中使用模型
确保生产环境中安装了必要的库：
```bash
pip install joblib scikit-learn
```

## 4. 集成到选材引擎

### 4.1 使用MLSelectionEngine
修改选材相关代码以使用机器学习引擎：

```python
from app.services.selection.ml_engine import MLSelectionEngine

# 初始化机器学习选材引擎
engine = MLSelectionEngine()

# 分析热点适用性
result = engine.analyze_hotspot_suitability(hotspot, platform)
```

### 4.2 混合使用策略
当前实现支持自动回退机制，当机器学习模型不可用时会自动使用基于规则的分析方法。

## 5. 模型更新与维护

### 5.1 定期重新训练
建议定期使用新数据重新训练模型以保持准确性：
1. 导出最新的采集数据
2. 在Windows环境中重新训练模型
3. 部署新模型到生产环境

### 5.2 A/B测试
可以同时运行基于规则和基于机器学习的选材引擎，对比效果：
```python
# 基于规则的引擎
rule_result = rule_engine.analyze_hotspot_suitability(hotspot, platform)

# 基于机器学习的引擎
ml_result = ml_engine.analyze_hotspot_suitability(hotspot, platform)

# 对比结果
```

## 6. 性能优化建议

### 6.1 模型选择
- 对于2核2G的生产环境，建议使用轻量级模型如RandomForest
- 避免使用计算密集型模型如深度神经网络

### 6.2 特征工程
- 选择计算成本低但有效的特征
- 避免在生产环境中进行复杂的文本处理

### 6.3 缓存机制
- 对于重复的查询，可以使用缓存减少重复计算
- 考虑使用LRU缓存等机制

## 7. 故障处理

### 7.1 模型加载失败
系统会自动回退到基于规则的选材引擎，确保服务不中断。

### 7.2 预测准确性问题
- 检查训练数据是否具有代表性
- 考虑增加更多特征或调整模型参数
- 定期更新模型以适应内容变化

通过这种方式，您可以充分利用Windows环境的强大计算能力进行模型训练，同时在资源受限的生产环境中使用训练好的模型提供智能选材服务。