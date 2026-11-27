package fr.kfsmeteo.widget;
import android.content.*;
import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
final class Kfs {
 static final String BASE="https://kfs-meteo.fr";
 static final ZoneId PARIS=ZoneId.of("Europe/Paris");
 static android.content.SharedPreferences prefs(Context c){return c.getSharedPreferences("kfs",0);}
 static boolean valid(String code){return code.matches("(?:[0-9]{5}|2[AB][0-9]{3})");}
 static JSONObject get(String path)throws Exception{
  HttpURLConnection c=(HttpURLConnection)new URL(BASE+path).openConnection();
  c.setConnectTimeout(10000);c.setReadTimeout(18000);c.setRequestProperty("Accept","application/json");c.setInstanceFollowRedirects(false);
  try{if(c.getResponseCode()!=200)throw new IOException("HTTP "+c.getResponseCode());
   try(InputStream in=c.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>3000000)throw new IOException("Réponse trop grande");}return new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));}
  }finally{c.disconnect();}
 }
 static String deg(JSONObject j,String k){double d=j==null?Double.NaN:j.optDouble(k,Double.NaN);return Double.isFinite(d)?Math.round(d)+"°":"—";}
 static String weather(JSONObject j){int c=j==null?-1:j.optInt("code",-1);if(c<0)return "Indisponible";if(c==0)return "☀ Clair";if(c<=2)return "⛅ Éclaircies";if(c==3)return "☁ Couvert";if(c==45||c==48)return "Brouillard";if(c==56||c==57||c==66||c==67)return "Verglas possible";if(c==71||c==73||c==75||c==77||c==85||c==86)return "❄ Neige";if(c>=95)return "⚡ Orages";return "Pluie";}
 static String now(){return ZonedDateTime.now(PARIS).format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH':00'",Locale.ROOT));}
 static JSONObject row(JSONArray a,String key,String value){if(a!=null)for(int i=0;i<a.length();i++){JSONObject j=a.optJSONObject(i);if(j!=null&&value.equals(j.optString(key)))return j;}return null;}
 static boolean fresh(JSONObject j){try{long age=Duration.between(Instant.parse(j.getString("fetched_utc")),Instant.now()).toMinutes();return age>=-5&&age<=360;}catch(Exception e){return false;}}
}