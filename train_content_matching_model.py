#!/usr/bin/env python3
"""
内容匹配模型训练脚本
此脚本用于在Windows环境下训练内容匹配模型，然后部署到生产环境
"""

import json
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score
import joblib
import jieba
import re
from typing import List, Dict, Any

# 模拟平台偏好数据（实际应用中应从配置文件中读取）
PLATFORM_PREFERENCES = {
    "weibo": ["社会热点", "娱乐资讯", "生活分享", "明星", "八卦", "热搜"],
    "zhihu": ["科技专业分析", "技术讨论", "实用技巧", "资源盘点", "深度好文"],
    "toutiao": ["实时政策快讯", "社会新闻摘要", "科技热点短讯", "大众化话题"],
    "xiaohongshu": ["视觉化干货", "穿搭攻略", "家居改造", "设计分享", "生活方式"]
}

def preprocess_text(text: str) -> str:
    """
    文本预处理函数
    """
    # 去除特殊字符和数字
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\d+', '', text)
    
    # 中文分词
    words = jieba.cut(text)
    return ' '.join(words)

def generate_training_data(sample_size: int = 1000) -> pd.DataFrame:
    """
    生成模拟训练数据
    实际应用中应从真实数据中提取
    """
    # 模拟热点标题数据
    sample_titles = [
        "又一家电巨头官宣造车",
        "天气下雨时鸟都在干嘛？",
        "小型创业指南 #干货",
        "江苏省委书记为泰州队颁奖",
        "苏超泰州队冠军",
        "中国人有7张太空全家福了",
        "你好星期六下期张凌赫",
        "泰州金灿灿",
        "DRG早点 回家吧",
        "无限暖暖",
        "全国1%人口抽样调查",
        "久酷采访",
        "泰州 一黑到底",
        "最新Python编程技巧分享",
        "今日穿搭指南：秋季时尚搭配",
        "科技行业最新发展趋势分析",
        "人工智能在医疗领域的应用",
        "5G技术改变未来生活",
        "新能源汽车市场前景展望",
        "区块链技术原理详解"
    ]
    
    # 扩展数据集
    titles = []
    platforms = []
    
    for _ in range(sample_size):
        title = np.random.choice(sample_titles)
        platform = np.random.choice(list(PLATFORM_PREFERENCES.keys()))
        
        titles.append(title)
        platforms.append(platform)
    
    return pd.DataFrame({
        'title': titles,
        'platform': platforms
    })

def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    特征提取
    """
    # 文本预处理
    df['processed_title'] = df['title'].apply(preprocess_text)
    
    # 计算与各平台偏好的匹配度
    for platform, preferences in PLATFORM_PREFERENCES.items():
        df[f'{platform}_match_score'] = df['title'].apply(
            lambda x: sum(1 for pref in preferences if pref in x) / len(preferences)
        )
    
    return df

def train_model():
    """
    训练内容匹配模型
    """
    print("🚀 开始训练内容匹配模型...")
    
    # 生成训练数据
    print("   生成训练数据...")
    df = generate_training_data(2000)
    
    # 特征提取
    print("   提取特征...")
    df = extract_features(df)
    
    # 准备特征和标签
    feature_columns = [f'{p}_match_score' for p in PLATFORM_PREFERENCES.keys()]
    X = df[feature_columns]
    y = df['platform']
    
    # 划分训练集和测试集
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # 训练模型
    print("   训练模型...")
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # 评估模型
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"   模型准确率: {accuracy:.4f}")
    
    # 保存模型和向量化器
    print("   保存模型...")
    joblib.dump(model, 'content_matching_model.pkl')
    joblib.dump(PLATFORM_PREFERENCES, 'platform_preferences.pkl')
    
    print("✅ 模型训练完成!")
    print(f"   模型文件: content_matching_model.pkl")
    print(f"   平台偏好文件: platform_preferences.pkl")
    
    return model

def test_model():
    """
    测试模型
    """
    print("\n🔍 测试模型...")
    
    # 加载模型
    model = joblib.load('content_matching_model.pkl')
    
    # 测试样例
    test_titles = [
        "江苏省委书记为泰州队颁奖",
        "最新Python编程技巧分享",
        "今日穿搭指南：秋季时尚搭配",
        "人工智能在医疗领域的应用"
    ]
    
    # 提取特征
    test_data = pd.DataFrame({'title': test_titles})
    test_data = extract_features(test_data)
    
    feature_columns = [f'{p}_match_score' for p in PLATFORM_PREFERENCES.keys()]
    X_test = test_data[feature_columns]
    
    # 预测
    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)
    
    print("   测试结果:")
    for i, title in enumerate(test_titles):
        print(f"     标题: {title}")
        print(f"     预测平台: {predictions[i]}")
        print(f"     置信度: {max(probabilities[i]):.4f}")
        print()

if __name__ == "__main__":
    # 训练模型
    model = train_model()
    
    # 测试模型
    test_model()
    
    print("\n🎉 模型训练和测试完成!")
    print("   您可以将生成的模型文件部署到生产环境使用")