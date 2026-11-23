import {onMounted,onUnmounted,watch,type Ref} from 'vue'
export function useDismissible(root:Ref<HTMLElement|null>,open:Ref<boolean>,trigger?:Ref<HTMLElement|null>){
 const outside=(event:Event)=>{if(open.value&&!root.value?.contains(event.target as Node))open.value=false}
 const key=(event:KeyboardEvent)=>{if(open.value&&event.key==='Escape'){open.value=false;trigger?.value?.focus()}}
 const blur=()=>{open.value=false}
 onMounted(()=>{document.addEventListener('pointerdown',outside);document.addEventListener('focusin',outside);document.addEventListener('keydown',key);window.addEventListener('blur',blur)})
 onUnmounted(()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',outside);document.removeEventListener('keydown',key);window.removeEventListener('blur',blur)})
 return {close:()=>{open.value=false}}
}
