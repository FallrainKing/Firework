import type {Collection} from '@/api/types'
export type CollectionNode=Collection & {depth:number;hasChildren:boolean}

/** Parent-first rows for both navigation trees; searches retain ancestor context. */
export function collectionTree(items:Collection[],collapsed:ReadonlySet<number>=new Set(),query=''):CollectionNode[]{
 const nodes=new Map(items.map(c=>[c.id,c])),children=new Map<number|null,Collection[]>()
 for(const c of items){const parent=c.parent_id&&nodes.has(c.parent_id)?c.parent_id:null;children.set(parent,[...(children.get(parent)??[]),c])}
 const q=query.trim().toLowerCase(),allowed=new Set<number>()
 if(q)for(const c of items){if(!(c.path??c.name).toLowerCase().includes(q))continue;let node:Collection|undefined=c;const seen=new Set<number>();while(node&&!seen.has(node.id)){seen.add(node.id);allowed.add(node.id);node=node.parent_id?nodes.get(node.parent_id):undefined}}
 const rows:CollectionNode[]=[],seen=new Set<number>()
 function visit(parent:number|null,depth:number){for(const c of children.get(parent)??[]){if(seen.has(c.id)||(q&&!allowed.has(c.id)))continue;seen.add(c.id);rows.push({...c,depth,hasChildren:!!children.get(c.id)?.length});if(q||!collapsed.has(c.id))visit(c.id,depth+1)}}
 visit(null,0);return rows
}
