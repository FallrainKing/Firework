from agent_runner.streaming import LiveText

def event(text):return {'type':'stream_event','event':{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':text}}}

def test_partial_visible_text_and_completed_message_do_not_duplicate():
    live=LiveText();assert live.consume(event('Hello'))=='Hello'
    assert live.consume(event(' world'))=='Hello world'
    assert live.consume({'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'private'}}}) is None
    assert live.consume({'type':'assistant','message':{'content':[{'type':'text','text':'Hello world'}]}})=='Hello world'
    live.consume({'type':'stream_event','event':{'type':'message_start'}})
    assert live.consume(event('Next'))=='Hello world\n\nNext'
    assert live.consume({'parent_tool_use_id':'sub','type':'assistant','message':{'content':[{'type':'text','text':'hidden'}]}}) is None

def test_fragmented_secret_is_not_exposed_in_snapshot():
    from agent_runner.connections import redact
    key='secret-token-for-testing'
    for n in range(1,len(key)+1):
        text=LiveText.safe_prefix('Answer '+key[:n],key)
        safe=redact({'answer':text},key)['answer']
        assert not safe.endswith(key[:n])
