/** Safe UI messages; never render provider errors or credential values. */
export function loginError(status:number,detail?:string,retryAfter?:string|null):string {
  if(status===429) {
    const seconds=Number(retryAfter);
    return Number.isFinite(seconds)&&seconds>0
      ? "Слишком много попыток. Повторите вход через "+Math.ceil(seconds/60)+" мин."
      : "Слишком много попыток. Попробуйте позже.";
  }
  if(status===401)return "Неверный логин или пароль.";
  if(status===403)return detail==="CSRF_ORIGIN"
    ? "Ошибка проверки адреса страницы. Откройте панель по настроенному адресу и повторите вход."
    : "Ошибка проверки безопасности страницы. Обновите страницу и повторите вход.";
  if(status===400||status===422)return "Проверьте формат логина и пароля.";
  return "Сервер временно недоступен. Попробуйте позже.";
}
