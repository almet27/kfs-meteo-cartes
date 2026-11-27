package fr.kfsmeteo.widget;
import android.app.job.*;
import android.appwidget.AppWidgetManager;
import android.content.*;
import org.json.*;
public class WeatherJob extends JobService{
 static final int ID=275801,ONCE=275802;
 volatile boolean stopped=false;
 static void schedule(Context c){
  if(AppWidgetManager.getInstance(c).getAppWidgetIds(new ComponentName(c,WeatherWidget.class)).length==0)return;
  JobScheduler s=c.getSystemService(JobScheduler.class);ComponentName target=new ComponentName(c,WeatherJob.class);
  if(s.getPendingJob(ID)==null)s.schedule(new JobInfo.Builder(ID,target).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(3600000).build());
  if(s.getPendingJob(ONCE)==null)s.schedule(new JobInfo.Builder(ONCE,target).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setOverrideDeadline(30000).build());
 }
 @Override public boolean onStartJob(JobParameters p){stopped=false;new Thread(()->{String code=Kfs.prefs(this).getString("code","");if(Kfs.valid(code))try{JSONObject d=Kfs.get("/api/city-forecast?code="+code);if(!d.has("models")||!Kfs.fresh(d))throw new Exception();if(!stopped&&code.equals(Kfs.prefs(this).getString("code","")))Kfs.prefs(this).edit().putString("forecast",d.toString()).putBoolean("offline",false).apply();}catch(Exception e){if(code.equals(Kfs.prefs(this).getString("code","")))Kfs.prefs(this).edit().putBoolean("offline",true).apply();}if(!stopped){WeatherWidget.renderAll(this);jobFinished(p,false);}}).start();return true;}
 @Override public boolean onStopJob(JobParameters p){stopped=true;return true;}
}