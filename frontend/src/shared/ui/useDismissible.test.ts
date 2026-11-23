import {mount} from '@vue/test-utils'
import {defineComponent,ref} from 'vue'
import {it,expect} from 'vitest'
import {useDismissible} from './useDismissible'
it('closes on outside pointer/focus and Escape without swallowing internal actions',async()=>{
 const C=defineComponent({setup(){const root=ref<HTMLElement|null>(null),button=ref<HTMLElement|null>(null),open=ref(false);useDismissible(root,open,button);return {root,button,open}},template:'<div ref="root"><button ref="button" @click="open=!open">Menu</button><div v-if="open"><button class="inside">Action</button></div></div>'})
 const w=mount(C,{attachTo:document.body});await w.find('button').trigger('click');expect(w.find('.inside').exists()).toBe(true)
 await w.find('.inside').trigger('pointerdown');expect(w.find('.inside').exists()).toBe(true)
 document.body.dispatchEvent(new Event('pointerdown',{bubbles:true}));await w.vm.$nextTick();expect(w.find('.inside').exists()).toBe(false)
 await w.find('button').trigger('click');document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));await w.vm.$nextTick();expect(w.find('.inside').exists()).toBe(false);expect(document.activeElement).toBe(w.find('button').element)
 await w.find('button').trigger('click');const other=document.createElement('button');document.body.append(other);other.focus();await w.vm.$nextTick();expect(w.find('.inside').exists()).toBe(false)
 other.remove();w.unmount()
})
