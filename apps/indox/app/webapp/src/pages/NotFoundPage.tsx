import { Link, useLocation } from 'react-router-dom';
import { useContext } from 'react';
import { InstancesContext } from '../instancesContext';

/** The 404 route. Every unknown path used to render an EMPTY outlet under the tab strip — a screen
 *  with no words on it, indistinguishable from a page that was still loading. This one names the
 *  path, says it is not a screen, and points at the one that always exists. */
export default function NotFoundPage() {
  const { pathname } = useLocation();
  const { accounts } = useContext(InstancesContext);
  const inst = accounts.find((a) => a.enabled !== false)?.id;
  const home = inst ? `/i/${encodeURIComponent(inst)}/dashboard` : '/';
  return (
    <div className="callout" role="status" style={{ marginTop: 18 }}>
      <b>אין מסך בכתובת הזו.</b>{' '}
      <span className="mono" style={{ direction: 'ltr', unicodeBidi: 'isolate', wordBreak: 'break-all' }}>
        {pathname}
      </span>
      <div className="muted small" style={{ marginTop: 8 }}>
        ייתכן שהקישור ישן או שהמופע בכתובת שונה. המסכים הקיימים: לוח בקרה, מסמכים, סנכרון, יומן
        פעולות, הגדרות, בדיקות וחילוץ מסמכים.
      </div>
      <div style={{ marginTop: 10 }}>
        <Link className="btn sm" to={home}>ללוח הבקרה</Link>
      </div>
    </div>
  );
}
