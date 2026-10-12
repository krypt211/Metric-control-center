import {readFileSync} from "node:fs";
const issued = new Map();
export function fixtureInput(url){
 const helper=readFileSync(new URL("./session-fixture.py",import.meta.url),"utf8").replace(/^\uFEFF/,"");
 const source=readFileSync(url,"utf8").replace(/^\uFEFF/,"");
 // Code is passed through stdin, never interpolated into a shell command.
 return "import types,sys\nm=types.ModuleType('mcc_ui_sessions')\nexec("+JSON.stringify(helper)+",m.__dict__)\nsys.modules['mcc_ui_sessions']=m\nexec("+JSON.stringify(source)+")";
}
export async function fixtureSessionLogin(page,user){
 if(process.env.UI_SESSION_FIXTURES!=="true")return false;
 if(!user.cookies?.length)throw new Error("Fixture session was not issued");
 const base=process.env.UI_BASE_URL??"http://127.0.0.1:3000";
 if(!["127.0.0.1","localhost"].includes(new URL(base).hostname))throw new Error("Local fixture host required");
 const index=issued.get(user.id)??0;
 if(index>=user.cookies.length)throw new Error("Fixture sessions exhausted");
 issued.set(user.id,index+1);
 await page.context().addCookies([{...user.cookies[index],url:base}]);
 await page.goto("/");
 return true;
}
