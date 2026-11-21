import { api } from './client'
export interface BudgetValues { max_turns:number; max_output_tokens:number; max_calls:number; timeout_s:number; cost_mode:'disabled'|'cli_estimate_guard'; max_budget_usd:number|null }
export interface BudgetRef { id:string; revision:number }
export interface Budget extends BudgetRef {name:string; builtin:boolean; values:BudgetValues}
export interface BudgetList {budgets:Budget[];default_budget_id:string|null;settings_revision:number}
export interface BudgetPreview {effective:Record<string,number|null>;tools:string[];warning:string}
const base='/api/me/runner/budgets'
export const runnerBudgets={
 list:()=>api<BudgetList>(base),
 save:(name:string,values:BudgetValues,existing?:BudgetRef)=>api<Budget>(base+(existing?'/'+existing.id:''),{method:existing?'PATCH':'POST',body:{name,values,...(existing?{expected_revision:existing.revision}:{})}}),
 setDefault:(budget_id:string|null,expected_revision:number)=>api<BudgetList>(base+'/default',{method:'PUT',body:{budget_id,expected_revision}}),
 preview:(skill:string,budget:BudgetRef|null,inherit_skill=false)=>api<BudgetPreview>(base+'/preflight',{body:{skill,budget,inherit_skill}}),
}
