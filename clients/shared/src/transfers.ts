import type { ProjectJournal, SourceJournal } from './journal';

/** Concurrent media operations merge their completed fields into the saved source. */
export function rememberSourceChanges(project: ProjectJournal, source: SourceJournal, changes: Partial<SourceJournal>): ProjectJournal {
  const current = project.sources.find(item => item.sourceId === source.sourceId) ?? source;
  return {
    ...project,
    sources: [{ ...current, ...changes }, ...project.sources.filter(item => item.sourceId !== source.sourceId)],
  };
}
