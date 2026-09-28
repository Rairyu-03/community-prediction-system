import { test } from 'node:test';
import assert from 'node:assert/strict';
import { forecastYears, orderedYears, fillMissingPopulationYears, populationParameterIssues, MORTALITY_GROUPS } from '../src/forecastParameters.ts';

test('target years follow start and duration, excluding base year', () => {
  assert.deepEqual(forecastYears(2040,3), ['2041','2042','2043']);
  for (const args of [[null,5],[2026,0],[2026,1.5],[9900,100]]) assert.deepEqual(forecastYears(...args),[]);
});
test('target years first, reference years optional and preserved', () => {
  assert.deepEqual(orderedYears(['2041','2042'],['2026','2041','2036','2026'],false),['2041','2042']);
  assert.deepEqual(orderedYears(['2041','2042'],['2026','2041','2036','2026'],true),['2041','2042','2026','2036']);
});
test('explicit completion preserves zero, uses original nearest sources and never mutates input', () => {
  const data={startYear:2036,duration:3,birthRates:{全国:{2036:0,2038:4}},deathRates:{2036:{'0-4岁':.25}},sourceNotes:{birth:'资料来源'}};
  const before=structuredClone(data);
  const result=fillMissingPopulationYears(data,['2037','2038','2039'],['0-4岁','5-9岁']);
  assert.deepEqual(data,before);
  assert.equal(result.birthRates.全国['2037'],0);
  assert.equal(result.birthRates.全国['2038'],4);
  assert.equal(result.birthRates.全国['2039'],4);
  assert.equal(result.deathRates['2039']['0-4岁'],.25);
  assert.equal(result.deathRates['2039']['5-9岁'],undefined);
  assert.match(result.sourceNotes.birth,/沿用假设/);
});
test('completion extends predictions beyond old defaults and clears coverage errors', () => {
  const data={startYear:2040,duration:5,birthRates:{全国:{2036:4}},deathRates:{2036:Object.fromEntries(MORTALITY_GROUPS.map(g=>[g,.2]))}};
  assert.equal(populationParameterIssues(data).length,1);
  const result=fillMissingPopulationYears(data,forecastYears(2040,5),MORTALITY_GROUPS);
  assert.deepEqual(populationParameterIssues(result),[]);
  assert.equal(populationParameterIssues({...result,_pendingUniformDeath:{}}).length,1);
});
