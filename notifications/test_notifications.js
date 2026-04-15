// Test script for notification endpoints
// Run this with Node.js or in browser console

const baseUrl = 'http://localhost:8000/api'; // Adjust if different

// Test data
const testProjectId = 1; // Replace with actual project ID
const testDprId = 1; // Replace with actual DPR ID

// Test functions
async function testProjectCreated() {
    try {
        const response = await fetch(`${baseUrl}/notifications/project-created/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: testProjectId })
        });
        const result = await response.json();
        console.log('Project Created Notification:', result);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function testTeamLeadAssigned() {
    try {
        const response = await fetch(`${baseUrl}/notifications/team-lead-assigned/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: testProjectId, user_id: 2 }) // test_team_lead user_id
        });
        const result = await response.json();
        console.log('Team Lead Assigned Notification:', result);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function testSiteEngineerAssigned() {
    try {
        const response = await fetch(`${baseUrl}/notifications/site-engineer-assigned/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: testProjectId, user_id: 3 }) // test_site_engineer user_id
        });
        const result = await response.json();
        console.log('Site Engineer Assigned Notification:', result);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function testDprSubmitted() {
    try {
        const response = await fetch(`${baseUrl}/notifications/dpr-submitted/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dpr_id: testDprId })
        });
        const result = await response.json();
        console.log('DPR Submitted Notification:', result);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function testDprApproved() {
    try {
        const response = await fetch(`${baseUrl}/notifications/dpr-approved/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dpr_id: testDprId })
        });
        const result = await response.json();
        console.log('DPR Approved Notification:', result);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function testDprRejected() {
    try {
        const response = await fetch(`${baseUrl}/notifications/dpr-rejected/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dpr_id: testDprId })
        });
        const result = await response.json();
        console.log('DPR Rejected Notification:', result);
    } catch (error) {
        console.error('Error:', error);
    }
}

// Run all tests
async function runAllTests() {
    console.log('Testing notification endpoints...');
    await testProjectCreated();
    await testTeamLeadAssigned();
    await testSiteEngineerAssigned();
    await testDprSubmitted();
    await testDprApproved();
    await testDprRejected();
    console.log('All tests completed. Check emails at:');
    console.log('- ahiresandesh4@gmail.com (Team Lead)');
    console.log('- sanchitahire191@gmail.com (Site Engineer)');
}

// Uncomment to run all tests
// runAllTests();