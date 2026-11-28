package fr.kfsmeteo.widget;
import android.app.*;
import android.appwidget.*;
import android.content.*;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.RemoteViews;
import org.json.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
public class WeatherWidget extends AppWidgetProvider{
 @Override public void onUpdate(Context c,AppWidgetManager m,int[] ids){renderAll(c);WeatherJob.schedule(c);}
 @Override public void onAppWidgetOptionsChanged(Context c,AppWidgetManager m,int id,Bundle b){render(c,m,id);}
 @Override public void onDisabled(Context c){c.getSystemService(android.app.job.JobScheduler.class).cancel(WeatherJob.ID);}
 static void renderAll(Context c){AppWidgetManager m=AppWidgetManager.getInstance(c);for(int id:m.getAppWidgetIds(new ComponentName(c,WeatherWidget.class)))render(c,m,id);}
 static void render(Context c,AppWidgetManager m,int id){
  RemoteViews v=new RemoteViews(c.getPackageName(),R.layout.weather_widget);
  android.content.SharedPreferences p=Kfs.prefs(c);java.util.LinkedHashMap<String,String> cities=Kfs.cities(c);
  if(cities.size()>1){renderMulti(c,m,id,v,cities);return;}String code=cities.isEmpty()?"":cities.keySet().iterator().next(),city=cities.isEmpty()?"Choisir une commune":cities.get(code);
  Intent intent=Kfs.valid(code)?new Intent(Intent.ACTION_VIEW,Uri.parse(Kfs.BASE+"/?city-code="+code+"#city-result")):new Intent(c,MainActivity.class);
  v.setOnClickPendingIntent(R.id.root,PendingIntent.getActivity(c,id,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));
  v.setViewVisibility(R.id.temp,View.VISIBLE);v.setViewVisibility(R.id.condition,View.VISIBLE);v.setTextViewText(R.id.city,city);v.setTextViewText(R.id.temp,"—");v.setTextViewText(R.id.condition,Kfs.valid(code)?"Prévisions indisponibles":"Touchez pour configurer");v.setTextViewText(R.id.source,"");
  v.setViewVisibility(R.id.hours,View.GONE);v.setViewVisibility(R.id.days,View.GONE);
  try{JSONObject d=Kfs.forecast(c,code);if(!Kfs.fresh(d))throw new Exception();JSONObject models=d.getJSONObject("models");String now=Kfs.now(),date=now.substring(0,10),model="IFS";JSONObject data=models.optJSONObject("ifs"),h=Kfs.row(data==null?null:data.optJSONArray("hours"),"time",now);if(h==null){model="GFS";data=models.optJSONObject("gfs");h=Kfs.row(data==null?null:data.optJSONArray("hours"),"time",now);}if(h==null)throw new Exception();
   JSONArray hours=data.optJSONArray("hours"),days=data.optJSONArray("days");JSONObject today=Kfs.row(days,"date",date);
   v.setTextViewText(R.id.temp,Kfs.deg(h,"temp"));v.setTextViewText(R.id.condition,Kfs.weather(h)+" · "+Kfs.deg(today,"min")+"/"+Kfs.deg(today,"max"));
   Instant updated=Instant.parse(d.getString("fetched_utc"));boolean old=d.optBoolean("stale")||Duration.between(updated,Instant.now()).toMinutes()>180||p.getBoolean("offline_"+code,false);
   v.setTextViewText(R.id.source,model+" · Prévision "+(old?"ancienne · ":"· ")+updated.atZone(Kfs.PARIS).format(DateTimeFormatter.ofPattern("HH:mm")));
   Bundle options=m.getAppWidgetOptions(id);int width=options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH,0),height=options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT,0);
   if(width>=220&&height>=145&&hours!=null){StringBuilder s=new StringBuilder();int count=0;for(int i=0;i<hours.length()&&count<4;i++){JSONObject x=hours.optJSONObject(i);if(x==null)continue;String t=x.optString("time");if(t.length()<16||t.compareTo(now)<=0)continue;if(count++>0)s.append("  ·  ");s.append(t.substring(11,13)).append("h ").append(Kfs.deg(x,"temp"));}if(count>0){v.setTextViewText(R.id.hours,s);v.setViewVisibility(R.id.hours,View.VISIBLE);}}
   if(width>=220&&height>=240&&days!=null){StringBuilder s=new StringBuilder();int count=0;for(int i=0;i<days.length()&&count<3;i++){JSONObject x=days.optJSONObject(i);if(x==null)continue;String t=x.optString("date");if(t.length()!=10||t.compareTo(date)<=0)continue;if(count++>0)s.append("\n");s.append(t.substring(8,10)).append("/").append(t.substring(5,7)).append("  ").append(Kfs.weather(x)).append("  ").append(Kfs.deg(x,"min")).append("/").append(Kfs.deg(x,"max"));}if(count>0){v.setTextViewText(R.id.days,s);v.setViewVisibility(R.id.days,View.VISIBLE);}}
  }catch(Exception ignored){}
  m.updateAppWidget(id,v);
 }
 static void renderMulti(Context c,AppWidgetManager m,int id,RemoteViews v,java.util.LinkedHashMap<String,String> cities){
  Bundle opts=m.getAppWidgetOptions(id);int width=opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH,0),height=opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT,0),limit=width>=220&&height>=145?4:2;
  String now=Kfs.now(),date=now.substring(0,10);StringBuilder lines=new StringBuilder();boolean old=false;int count=0;
  for(java.util.Map.Entry<String,String> e:cities.entrySet()){if(count>=limit)break;String code=e.getKey();JSONObject d=Kfs.forecast(c,code),models=d.optJSONObject("models"),h=null,today=null;
   if(Kfs.fresh(d)&&models!=null){JSONObject data=models.optJSONObject("ifs");h=Kfs.row(data==null?null:data.optJSONArray("hours"),"time",now);if(h==null){data=models.optJSONObject("gfs");h=Kfs.row(data==null?null:data.optJSONArray("hours"),"time",now);}if(data!=null)today=Kfs.row(data.optJSONArray("days"),"date",date);}
   boolean stale=false;try{stale=d.optBoolean("stale")||Duration.between(Instant.parse(d.getString("fetched_utc")),Instant.now()).toMinutes()>180||Kfs.prefs(c).getBoolean("offline_"+code,false);}catch(Exception ignored){}old|=stale&&h!=null;
   if(count++>0)lines.append("\n");lines.append(e.getValue()).append("  ").append(Kfs.deg(h,"temp"));if(width>=220){lines.append("  ").append(h==null?"Indisponible":Kfs.weather(h));if(height>=240&&h!=null)lines.append("  ").append(Kfs.deg(today,"min")).append("/").append(Kfs.deg(today,"max"));}if(stale&&h!=null)lines.append(" *");
  }
  v.setTextViewText(R.id.city,cities.size()+" communes");v.setViewVisibility(R.id.temp,View.GONE);v.setViewVisibility(R.id.condition,View.GONE);v.setViewVisibility(R.id.hours,View.GONE);v.setViewVisibility(R.id.days,View.VISIBLE);v.setTextViewText(R.id.days,lines.toString());v.setTextViewText(R.id.source,(old?"* Prévision ancienne":"Températures prévues")+(cities.size()>count?" · +"+(cities.size()-count)+" autres":""));
  Intent intent=new Intent(c,MainActivity.class);v.setOnClickPendingIntent(R.id.root,PendingIntent.getActivity(c,id,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));m.updateAppWidget(id,v);
 }
}