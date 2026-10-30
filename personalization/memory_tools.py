"""Bind legacy memory skills to the request's authorized memory objects."""


def memory_tool_result(name, arguments, previous, coordinator):
    if name == 'search_history':
        # Never accept a model-supplied session ID or construct a fresh memory client.
        messages = previous.get('history', [])
        return {'answer': '本轮允许的会话历史：' + str(messages) if messages else '本轮没有可用的历史记录。',
                'total_messages': len(messages)}
    if name == 'search_similar_cases':
        memory = coordinator.long_term_memory
        if not memory.enabled:
            return {'answer':'本轮未授权长期记忆检索。', 'total_found':0}
        results = memory.search_similar_sessions(query=str(arguments.get('query',''))[:1000], limit=3)
        return {'answer':'当前账号已授权的历史摘要，仅作历史参考：' + str(results), 'total_found':len(results)}
    return None
