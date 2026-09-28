import { useEffect, useState } from "react";
import type { InputHTMLAttributes } from "react";

// Keep text while editing: clearing an optional number must not immediately
// turn into Number("") === 0 and reinsert a leading zero.
export function NumericInput({value, onNumberChange, ...props}: Omit<InputHTMLAttributes<HTMLInputElement>, "value"|"onChange"> & {value: number | undefined | null; onNumberChange:(value:number|undefined)=>void}) {
  const [text,setText] = useState(value == null ? "" : String(value));
  useEffect(()=>setText(value == null ? "" : String(value)),[value]);
  return <input {...props} type="number" value={text} onFocus={e=>{if(e.currentTarget.value==="0")e.currentTarget.select();}} onChange={e=>{setText(e.target.value);onNumberChange(e.target.value===""?undefined:Number(e.target.value));}} onBlur={()=>{if(text!=="")setText(String(Number(text)));}} />;
}
