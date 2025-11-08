import json
import os

# 定义文件路径
file_path = os.path.join(os.path.dirname(__file__), 'collect.json')

# 读取JSON文件
def read_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        # 尝试修复文件，确保文件内容是有效的JSON数组
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # 确保文件以[]包围
            if not content.startswith('['):
                content = '[' + content
            if not content.endswith(']'):
                content = content + ']'
            try:
                data = json.loads(content)
                print("成功修复并解析JSON文件")
                return data
            except json.JSONDecodeError:
                print("无法修复JSON文件")
                return []
    except Exception as e:
        print(f"读取文件错误: {e}")
        return []

# 保存JSON文件
def save_json_file(data, file_path):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"成功保存文件到 {file_path}")
    except Exception as e:
        print(f"保存文件错误: {e}")

# 去重函数
def deduplicate_items(items):
    if not items:
        return [], 0
    
    # 使用集合来去重，基于标题和URL的组合
    seen = set()
    unique_items = []
    
    for item in items:
        # 创建一个唯一标识符，基于标题和URL
        # 有些项目可能没有URL字段，所以我们使用title作为备选
        title = item.get('title', '')
        url = item.get('url', '')
        
        # 如果title不存在，则跳过这个项目
        if not title:
            continue
            
        # 创建唯一键
        key = f"{title}:{url}" if url else title
        
        if key not in seen:
            seen.add(key)
            unique_items.append(item)
    
    # 计算去重数量
    duplicate_count = len(items) - len(unique_items)
    return unique_items, duplicate_count

# 主函数
def main():
    print(f"开始处理文件: {file_path}")
    
    # 读取原始数据
    items = read_json_file(file_path)
    
    if not items:
        print("没有数据可处理")
        return
    
    print(f"原始数据数量: {len(items)}")
    
    # 去重
    unique_items, duplicate_count = deduplicate_items(items)
    
    print(f"去重后数据数量: {len(unique_items)}")
    print(f"去除重复数量: {duplicate_count}")
    
    # 保存去重后的数据
    save_json_file(unique_items, file_path)
    
    # 可选：备份原始数据
    backup_path = file_path + '.backup'
    save_json_file(items, backup_path)
    print(f"原始数据已备份到: {backup_path}")

if __name__ == "__main__":
    main()