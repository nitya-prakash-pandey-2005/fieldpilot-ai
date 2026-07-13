import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';

export interface FieldIssue {
  id: string;
  project_id: string;
  zone_id: string;
  zone_code: string;
  issue_type: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  status: 'open' | 'resolved' | 'escalated' | 'dismissed';
  description: string;
  deviation_pct: number | null;
  measured_value: string | null;
  expected_value: string | null;
  worker_id: string | null;
  created_at: string;
  updated_at: string;
  resolved_by?: string;
  resolved_at?: string;
  resolution_note?: string;
  escalated_to?: string;
  escalated_at?: string;
  detected_by?: string;
  drawing_ref?: string;
}

export interface IssuesSummary {
  total: number;
  by_severity: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  open: number;
  resolved_today: number;
}

// Global EventTarget for sidebar updates
export const issuesEventTarget = new EventTarget();

export function useFieldIssues(projectId: string = 'default-project') {
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [summary, setSummary] = useState<IssuesSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newIssueId, setNewIssueId] = useState<string | null>(null);

  const fetchIssues = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/projects/${projectId}/issues`);
      if (!res.ok) throw new Error('Failed to fetch issues');
      const data = await res.json();
      setIssues(data.issues);
      setSummary(data.summary);
      setError(null);
      
      // Dispatch event to update sidebar
      issuesEventTarget.dispatchEvent(new CustomEvent('issues-updated', { detail: data.summary.open }));
    } catch (err: any) {
      setError(err.message);
      toast.error('Could not load issues');
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchIssues();
  }, [fetchIssues]);

  useEffect(() => {
    const eventSource = new EventSource(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/projects/${projectId}/issues/stream`);

    eventSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        
        if (event.type === 'ISSUE_CREATED') {
          // Add new issue to top
          if (event.issue) {
             setIssues(prev => [event.issue, ...prev]);
             setNewIssueId(event.issue.id);
             toast.error(`New issue detected — Zone ${event.issue.zone_code} · ${event.issue.issue_type}`);
             setTimeout(() => setNewIssueId(null), 1500); // Flash cyan for 1.5s
             
             // Update summary locally to avoid full fetch if possible, or just refetch
             fetchIssues();
          } else {
             // Fallback if the payload just gave the ID
             fetchIssues().then(() => {
                toast.error(`New issue detected`);
             });
          }
        } else if (event.type === 'ISSUE_RESOLVED') {
          setIssues(prev => prev.map(i =>
            i.id === event.issue_id
              ? { ...i, status: 'resolved' }
              : i
          ));
          fetchIssues(); // Refresh summary
        } else if (event.type === 'ISSUE_ESCALATED') {
          setIssues(prev => prev.map(i =>
            i.id === event.issue_id
              ? { ...i, status: 'escalated' }
              : i
          ));
          fetchIssues(); // Refresh summary
        }
      } catch (err) {
        console.error("Error parsing SSE data", err);
      }
    };

    return () => {
      eventSource.close();
    };
  }, [projectId, fetchIssues]);

  const resolveIssue = async (issueId: string, note: string) => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/issues/${issueId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolved_by_user_id: 'current_user', resolution_note: note })
      });
      if (!res.ok) throw new Error('Failed to resolve');
      
      // Card fades out and disappears from open issues list
      setIssues(prev => prev.filter(i => i.id !== issueId));
      
      // Update summary manually or fetch
      fetchIssues(); 
      toast.success('Issue marked as resolved');
      return true;
    } catch (err) {
      toast.error('Failed to resolve issue');
      return false;
    }
  };

  const escalateIssue = async (issueId: string, role: string, note: string) => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/issues/${issueId}/escalate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ escalated_by_user_id: 'current_user', escalate_to_role: role, note })
      });
      if (!res.ok) throw new Error('Failed to escalate');
      
      // Assuming escalated issues still show up but with escalated status
      setIssues(prev => prev.map(i => i.id === issueId ? { ...i, status: 'escalated' } : i));
      fetchIssues();
      toast.success(`Issue escalated to ${role}`);
      return true;
    } catch (err) {
      toast.error('Failed to escalate issue');
      return false;
    }
  };

  return {
    issues,
    setIssues,
    summary,
    isLoading,
    error,
    newIssueId,
    resolveIssue,
    escalateIssue,
    refetch: fetchIssues
  };
}
