import {describe,it,expect} from 'vitest'
import {collectionTree} from './collections'
const rows=[{id:1,name:'A',parent_id:null,path:'A'},{id:2,name:'B',parent_id:null,path:'B'},{id:3,name:'Child',parent_id:1,path:'A / Child'},{id:4,name:'Leaf',parent_id:3,path:'A / Child / Leaf'}]
describe('collection hierarchy',()=>{
 it('places descendants below their parent instead of mixing levels',()=>{expect(collectionTree(rows).map(c=>[c.id,c.depth])).toEqual([[1,0],[3,1],[4,2],[2,0]])})
 it('collapses only descendants and search restores ancestor context',()=>{expect(collectionTree(rows,new Set([1])).map(c=>c.id)).toEqual([1,2]);expect(collectionTree(rows,new Set([1]),'Leaf').map(c=>c.id)).toEqual([1,3,4])})
})
